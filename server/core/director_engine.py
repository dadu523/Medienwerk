import os
import subprocess
import logging
import json
import shutil
from pydub import AudioSegment
from pydub.silence import detect_silence
from server.core.youtube_downloader import download_youtube_video
from server.core.process_runner import run_process
from server.core.media_store import probe_media

def _run_process(args, stop_event=None):
    if stop_event is not None and stop_event.is_set():
        raise InterruptedError("Director job was cancelled")
    return run_process(args, stop_event=stop_event, timeout=3600, capture_output=True)


def run_director_pipeline(url: str, job_id: str, update_job_callback, remove_silence=True, add_punch_ins=True, add_sfx=True, *, output_dir=None, source_dir=None, final_path=None, stop_event=None, config=None):
    try:
        output_dir = output_dir or os.path.join("workspace", f"director_{job_id}")
        source_dir = source_dir or output_dir
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(source_dir, exist_ok=True)
        
        update_job_callback(job_id, step="Downloading Raw Video", progress=0.1)
        video_path = download_youtube_video(url, source_dir, stop_event=stop_event)
        source_probe = probe_media(video_path, expected_kind="video")
        source_has_audio = any(stream.get("type") == "audio" for stream in source_probe["metadata"]["streams"])
        if (remove_silence or add_sfx) and not source_has_audio:
            raise ValueError("Director silence removal and sound effects require an audio stream")
        
        final_out_path = final_path or os.path.join(output_dir, "final_master.mp4")
        current_video_path = video_path
        
        # Phase 2: Silence Trimmer Engine
        if remove_silence:
            update_job_callback(job_id, step="Scanning Audio Waveform for Dead Air", progress=0.3)
            # Extract audio
            audio_path = os.path.join(output_dir, "temp_audio.wav")
            _run_process(["ffmpeg", "-y", "-i", current_video_path, "-ac", "1", "-ar", "44100", audio_path], stop_event)
            
            # Detect silence
            audio = AudioSegment.from_wav(audio_path)
            # Silence threshold = -40dB, min silence length = 800ms
            silence_ranges = detect_silence(audio, min_silence_len=800, silence_thresh=-40)
            
            if silence_ranges:
                update_job_callback(job_id, step=f"Removing {len(silence_ranges)} silent gaps", progress=0.4)
                
                concat_path = os.path.join(output_dir, "concat.txt")
                
                non_silent_chunks = []
                last_end = 0.0
                video_duration = len(audio) / 1000.0
                
                with open(concat_path, "w", encoding="utf-8") as f:
                    for i, (start_ms, end_ms) in enumerate(silence_ranges):
                        start_s = start_ms / 1000.0
                        end_s = end_ms / 1000.0
                        
                        if start_s - last_end > 0.5: # Must have at least 0.5s of talking
                            chunk_path = os.path.join(output_dir, f"chunk_{i}.mp4")
                            # We re-encode to ensure precise cuts, using veryfast to speed it up
                            _run_process([
                                "ffmpeg", "-y", "-ss", str(last_end), "-to", str(start_s),
                                "-i", current_video_path,
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                                "-c:a", "aac",
                                chunk_path
                            ], stop_event)
                            f.write(f"file '{os.path.basename(chunk_path)}'\n")
                            non_silent_chunks.append(chunk_path)
                            
                        last_end = end_s
                        
                    if video_duration - last_end > 0.5:
                        chunk_path = os.path.join(output_dir, f"chunk_final.mp4")
                        _run_process([
                            "ffmpeg", "-y", "-ss", str(last_end),
                            "-i", current_video_path,
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                            "-c:a", "aac",
                            chunk_path
                        ], stop_event)
                        f.write(f"file '{os.path.basename(chunk_path)}'\n")
                        non_silent_chunks.append(chunk_path)
                
                # Concat all non-silent chunks
                trimmed_path = os.path.join(output_dir, "trimmed.mp4")
                _run_process(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path, "-c", "copy", trimmed_path], stop_event)
                
                current_video_path = trimmed_path

        # Phase 3: Punch-ins & SFX
        if add_punch_ins or add_sfx:
            update_job_callback(job_id, step="Transcribing Audio for Smart Cuts", progress=0.6)
            import whisper
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Director job was cancelled")
            model = whisper.load_model("base")
            result = model.transcribe(current_video_path, word_timestamps=True)
            if stop_event is not None and stop_event.is_set():
                raise InterruptedError("Director job was cancelled")
            
            high_impact = ["money", "secret", "viral", "crazy", "explosive", "hack", "truth", "insane"]
            
            sfx_times = []
            punch_in_times = []
            
            for segment in result.get("segments", []):
                for word_info in segment.get("words", []):
                    word = word_info['word'].strip().lower()
                    word = ''.join(e for e in word if e.isalnum())
                    
                    if word in high_impact:
                        sfx_times.append(word_info['start'])
                        punch_start = max(0, word_info['start'] - 0.2)
                        punch_in_times.append((punch_start, punch_start + 1.5))
            
            if punch_in_times or sfx_times:
                update_job_callback(job_id, step=f"Injecting {len(punch_in_times)} Punch-ins & {len(sfx_times)} SFX", progress=0.8)
                
                # Build FFmpeg command for dynamic punch-ins and audio mixing
                cmd = ["ffmpeg", "-y", "-i", current_video_path]
                filter_complex = ""
                
                # Setup video punch-in (15% zoom in center)
                if add_punch_ins and punch_in_times:
                    between_clauses = " + ".join([f"between(t,{start},{end})" for start, end in punch_in_times])
                    filter_complex += f"[0:v]split=2[base][z];[z]crop=iw*0.85:ih*0.85:(iw-iw*0.85)/2:(ih-ih*0.85)/2,scale=iw:ih[zoomed];[base][zoomed]overlay=enable='{between_clauses}'[vout];"
                else:
                    filter_complex += "[0:v]copy[vout];"
                
                # Setup SFX
                audio_inputs = 0
                if add_sfx and sfx_times:
                    swoosh_path = "assets/sfx/swoosh.wav"
                    if os.path.exists(swoosh_path):
                        cmd.extend(["-i", swoosh_path])
                        # delay the swoosh to match sfx_times
                        adelays = []
                        for idx, t in enumerate(sfx_times):
                            delay_ms = int(t * 1000)
                            filter_complex += f"[1:a]adelay={delay_ms}|{delay_ms}[sfx{idx}];"
                            adelays.append(f"[sfx{idx}]")
                        
                        amix_inputs = "".join(adelays)
                        filter_complex += f"[0:a]{amix_inputs}amix=inputs={len(sfx_times)+1}:duration=first:dropout_transition=2[aout]"
                    else:
                        filter_complex += "[0:a]acopy[aout]"
                else:
                    filter_complex += "[0:a]acopy[aout]"
                
                # Fallback cleanups in case acopy doesn't exist
                filter_complex = filter_complex.replace("[0:a]acopy[aout]", "[0:a]anull[aout]")
                filter_complex = filter_complex.replace("[0:v]copy[vout]", "[0:v]null[vout]")
                
                final_magic_path = os.path.join(output_dir, "magic_master.mp4")
                cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]", "-c:v", "libx264", "-c:a", "aac", final_magic_path])
                
                _run_process(cmd, stop_event)
                current_video_path = final_magic_path
                
        shutil.copy(current_video_path, final_out_path)
        
        update_job_callback(job_id, step="Finished Editing", progress=1.0, result=final_out_path)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        logging.error(f"Director Error: {e}")
        if stop_event is not None and stop_event.is_set():
            raise InterruptedError("Director job was cancelled") from e
        update_job_callback(job_id, step="Failed", progress=1.0, error=str(e))
        raise
