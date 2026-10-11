import os
import json
import logging
import math
import subprocess
import time
import requests
import uuid
import ffmpeg
from config import load_config
from api_clients import GoogleClient, WaveSpeedClient
from server.core.process_runner import run_process


def _timestamp_seconds(value: str) -> float:
    parts = str(value).split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    if len(parts) == 1:
        return float(parts[0])
    raise ValueError("Invalid scene timestamp")

class ExplainerEngine:
    def __init__(self, job_id: str, url: str, target_duration: str, language: str = "English", voice: str = "Kore", text_engine: str = "Gemini API", audio_engine: str = "WaveSpeed AI", on_progress: callable = None, *, config: dict | None = None, output_dir: str | None = None, source_dir: str | None = None, final_path: str | None = None, stop_event=None):
        self.job_id = job_id
        self.url = url
        self.target_duration = target_duration
        self.language = language
        self.voice = voice
        self.text_engine = text_engine
        self.audio_engine = audio_engine
        self.on_progress = on_progress
        self.stop_event = stop_event
        self.config = dict(config) if config is not None else load_config()
        # Override the text engine for this job
        self.config["TEXT_ENGINE"] = text_engine
        self.config["AUDIO_ENGINE"] = audio_engine
        self.config["VOICE_NAME"] = voice
        self.config["SPEAKER1"] = voice
        
        self.google_client = GoogleClient(self.config)
        self.wavespeed_client = WaveSpeedClient(
            self.config.get("WAVESPEED_API_KEY"), stop_event=self.stop_event
        ) if self.audio_engine == "WaveSpeed AI" else None
        
        self.workspace_dir = output_dir or os.path.join("outputs", f"explainer_{job_id}")
        os.makedirs(self.workspace_dir, exist_ok=True)
        
        self.source_dir = source_dir or self.workspace_dir
        os.makedirs(self.source_dir, exist_ok=True)
        self.video_path = os.path.join(self.source_dir, "raw_movie.mp4")
        self.audio_path = os.path.join(self.workspace_dir, "raw_audio.mp3")
        self.final_path = final_path or os.path.join(self.workspace_dir, "final_explainer.mp4")

    def _check_cancelled(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise InterruptedError("Explainer job was cancelled")

    def _run(self, args, **kwargs):
        self._check_cancelled()
        return run_process(args, stop_event=self.stop_event, timeout=3600, capture_output=kwargs.get("capture_output", True), text=kwargs.get("text", False), check=kwargs.get("check", True))

    def log(self, msg: str, progress: float):
        self._check_cancelled()
        logging.info(f"[Explainer {self.job_id}] {msg}")
        self.on_progress(msg, progress)

    def download_video(self):
        if os.path.exists(self.video_path):
            self.log(f"Skipping download, video already exists at {self.video_path}", 0.05)
        else:
            self.log(f"Fetching video from {self.url}...", 0.05)
            if self.url.startswith("http"):
                cmd = [
                    "yt-dlp",
                    "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4",
                    "-o", self.video_path,
                    self.url
                ]
                self._run(cmd, check=True)
            else:
                if not os.path.exists(self.url):
                    raise FileNotFoundError(f"Local file not found: {self.url}")
                import shutil
                shutil.copy2(self.url, self.video_path)
        self._check_cancelled()
        probe = ffmpeg.probe(self.video_path)
        try:
            self.source_duration = float(probe["format"]["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Source video has no valid duration") from exc
        if not math.isfinite(self.source_duration) or self.source_duration <= 0:
            raise ValueError("Source video has no valid duration")
            
    def extract_audio(self):
        if os.path.exists(self.audio_path):
            self.log("Audio already extracted. Skipping...", 0.15)
            return
            
        self.log("Extracting audio for transcription...", 0.15)
        self._run([
            "ffmpeg", "-y", "-i", self.video_path,
            "-vn", "-acodec", "libmp3lame", "-q:a", "4",
            self.audio_path
        ], check=True)
        
    def transcribe_audio(self) -> str:
        transcript_file = os.path.join(self.workspace_dir, "transcript.txt")
        if os.path.exists(transcript_file):
            self.log("Transcript already exists. Skipping Whisper...", 0.20)
            with open(transcript_file, 'r', encoding='utf-8') as f:
                return f.read()
                
        self.log("Transcribing audio using Whisper (this may take a while)...", 0.20)
        import whisper
        # Use 'tiny' model instead of 'base' to massively speed up local CPU transcription
        model = whisper.load_model("tiny")
        result = model.transcribe(self.audio_path)
        self._check_cancelled()
        
        transcript_text = ""
        for seg in result["segments"]:
            start = seg["start"]
            text = seg["text"].strip()
            # Format: [00:00:00] text
            start_str = time.strftime('%H:%M:%S', time.gmtime(start))
            transcript_text += f"[{start_str}] {text}\n"
            
        with open(transcript_file, 'w', encoding='utf-8') as f:
            f.write(transcript_text)
            
        return transcript_text

    def generate_script(self, transcript: str) -> list:
        script_file = os.path.join(self.workspace_dir, "script.json")
        if os.path.exists(script_file):
            self.log("Script already generated. Skipping AI generation...", 0.40)
            with open(script_file, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        self.log(f"Generating explainer script in {self.language} using {self.text_engine}...", 0.40)
        
        prompt = f"""You are an expert movie explainer script writer. Read this movie transcript and write a highly engaging {self.target_duration} explainer script.

CRITICAL REQUIREMENT:
Your entire output script (all 'text' fields) MUST be written in {self.language}. Do NOT write the voiceover in English unless {self.language} is English.

Return ONLY a valid JSON array of objects. Each object must have:
- "text": The voiceover text (1-3 sentences)
- "start_timestamp": The exact timestamp (HH:MM:SS) in the video from the transcript where the scene occurs.
- "end_timestamp": The exact timestamp (HH:MM:SS) where the scene ends.

Here is the transcript:
{transcript[:50000]} # Limit to 50k chars for safety if not using Gemini
"""
        response_text = self.google_client._generate_text(prompt, as_json=True)
        self._check_cancelled()
        
        # Clean JSON
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
            
        script_data = json.loads(response_text)
        if not isinstance(script_data, list) or not script_data:
            raise ValueError("Explainer provider returned no scenes")
        for scene in script_data:
            if not isinstance(scene, dict) or not str(scene.get("text", "")).strip():
                raise ValueError("Explainer provider returned a malformed scene")
            start = _timestamp_seconds(scene.get("start_timestamp"))
            end = _timestamp_seconds(scene.get("end_timestamp"))
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError("Explainer provider returned invalid scene timestamps")
        
        with open(script_file, 'w', encoding='utf-8') as f:
            json.dump(script_data, f, indent=4)
            
        return script_data
        
    def extract_and_sync_clips(self, script_data: list):
        self.log("Generating TTS and extracting video clips...", 0.60)
        
        merged_clips = []
        
        for idx, scene in enumerate(script_data):
            self.log(f"Processing scene {idx+1}/{len(script_data)}...", 0.60 + (0.20 * (idx/len(script_data))))
            
            final_scene_path = os.path.join(self.workspace_dir, f"scene_{idx}.mp4")
            if os.path.exists(final_scene_path):
                self.log(f"Scene {idx+1} already processed. Skipping...", 0.60 + (0.20 * (idx/len(script_data))))
                merged_clips.append(final_scene_path)
                continue
            
            text = scene["text"]
            clean_text = text.replace("*", "").replace("#", "").replace('"', '')
            start_ts = scene["start_timestamp"]
            end_ts = scene["end_timestamp"]
            
            # 1. Generate TTS
            tts_path = os.path.join(self.workspace_dir, f"tts_{idx}.mp3")
            
            if not os.path.exists(tts_path):
                if self.audio_engine == "WaveSpeed AI" and self.wavespeed_client:
                    self.wavespeed_client.text_to_speech(
                        self.config.get("WAVESPEED_AUDIO_MODEL", "elevenlabs/text-to-speech"), 
                        clean_text, 
                        tts_path, 
                        voice=self.voice
                    )
                else:
                    self.google_client.generate_tts(text, tts_path, {"SPEAKER1": self.voice})
                self._check_cancelled()
            
            # Get TTS duration
            probe = ffmpeg.probe(tts_path)
            tts_duration = float(probe['format']['duration'])
            
            start_sec = _timestamp_seconds(start_ts)
            end_sec = _timestamp_seconds(end_ts)
            duration = end_sec - start_sec
            source_duration = getattr(self, "source_duration", None)
            if (
                not math.isfinite(start_sec) or not math.isfinite(end_sec)
                or start_sec < 0 or end_sec <= start_sec
                or (source_duration is not None and end_sec > source_duration)
            ):
                raise ValueError(f"Explainer scene {idx + 1} is outside the source video")
            
            # Create Subtitle File for this scene
            import pysubs2
            import textwrap
            subs = pysubs2.SSAFile()
            
            font = self.config.get("CAPTION_FONT", "Arial")
            theme = self.config.get("CAPTION_THEME", "default")
            
            subs.styles["Default"].fontname = font
            subs.styles["Default"].fontsize = 24
            subs.styles["Default"].alignment = 2
            subs.styles["Default"].marginv = 30
            subs.styles["Default"].borderstyle = 1
            
            if theme == "viral_yellow":
                subs.styles["Default"].primarycolor = pysubs2.Color(255, 255, 0)
                subs.styles["Default"].outlinecolor = pysubs2.Color(0, 0, 0)
                subs.styles["Default"].backcolor = pysubs2.Color(0, 0, 0, 128)
                subs.styles["Default"].outline = 3
            elif theme == "neon_cyber":
                subs.styles["Default"].primarycolor = pysubs2.Color(0, 255, 255)
                subs.styles["Default"].outlinecolor = pysubs2.Color(255, 0, 255)
                subs.styles["Default"].backcolor = pysubs2.Color(0, 0, 0, 0)
                subs.styles["Default"].outline = 4
            elif theme == "black_white":
                subs.styles["Default"].primarycolor = pysubs2.Color(0, 0, 0)
                subs.styles["Default"].outlinecolor = pysubs2.Color(255, 255, 255)
                subs.styles["Default"].backcolor = pysubs2.Color(255, 255, 255, 128)
                subs.styles["Default"].outline = 3
            else:
                subs.styles["Default"].primarycolor = pysubs2.Color(255, 255, 255)
                subs.styles["Default"].outlinecolor = pysubs2.Color(0, 0, 0)
                subs.styles["Default"].backcolor = pysubs2.Color(0, 0, 0, 128)
                subs.styles["Default"].outline = 2
            
            wrapped_text = "\\N".join(textwrap.wrap(clean_text, width=45))
            subs.append(pysubs2.SSAEvent(start=0, end=int(tts_duration * 1000), text=wrapped_text))
            
            ass_path = os.path.join(self.workspace_dir, f"captions_{idx}.ass")
            subs.save(ass_path)
            
            ass_path_abs = os.path.abspath(ass_path).replace('\\', '/')
            ass_path_ff = ass_path_abs.replace(':', '\\:')
            
            # 2. Extract video clip and burn subtitles
            clip_path = os.path.join(self.workspace_dir, f"clip_{idx}.mp4")
            self._run([
                "ffmpeg", "-y", "-ss", str(start_sec), "-i", self.video_path,
                "-t", str(tts_duration),
                "-an", # Remove original audio
                "-vf", f"subtitles='{ass_path_ff}'",
                "-c:v", "libx264", "-preset", "ultrafast",
                clip_path
            ], check=True)
            
            # 3. Merge TTS + Synced Video
            final_scene_path = os.path.join(self.workspace_dir, f"scene_{idx}.mp4")
            self._run([
                "ffmpeg", "-y", "-i", clip_path, "-i", tts_path,
                "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
                final_scene_path
            ], check=True)
            
            merged_clips.append(final_scene_path)
            
            # Pace out requests to prevent hitting API rate limits (Gemini free tier allows ~15 RPM)
            if idx < len(script_data) - 1:
                self._check_cancelled()
                time.sleep(2.5)
            
        return merged_clips
        
    def merge_all(self, clip_paths: list):
        if os.path.exists(self.final_path):
            self.log("Explainer video already complete!", 1.0)
            return self.final_path
            
        self.log("Merging final video...", 0.90)
        
        list_file = os.path.join(self.workspace_dir, "clips.txt")
        with open(list_file, 'w') as f:
            for cp in clip_paths:
                f.write(f"file '{os.path.basename(cp)}'\n")
                
        self._run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
            "-c", "copy",
            self.final_path
        ], check=True)
        
        self.log("Explainer video complete!", 1.0)
        return self.final_path

    def process(self):
        try:
            self.download_video()
            self.extract_audio()
            transcript = self.transcribe_audio()
            script_data = self.generate_script(transcript)
            clips = self.extract_and_sync_clips(script_data)
            return self.merge_all(clips)
        except Exception as e:
            self.log(f"Failed: {str(e)}", 1.0)
            raise e
