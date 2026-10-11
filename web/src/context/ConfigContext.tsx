"use client";

import React, { createContext, useContext, useState, useEffect, useRef, ReactNode } from "react";
import { apiRequest, errorMessage } from "@/lib/api";

interface ConfigContextType {
  config: Record<string, any>;
  updateConfig: (key: string, value: any) => void;
  secretDrafts: Record<string, string>;
  updateSecret: (key: string, value: string) => void;
  clearSecret: (key: string) => void;
  saveConfig: () => Promise<void>;
  status: string;
  error: string | null;
}

const ConfigContext = createContext<ConfigContextType | undefined>(undefined);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Record<string, any>>({});
  const configRef = useRef<Record<string, any>>({});
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [deleteSecrets, setDeleteSecrets] = useState<string[]>([]);
  const dirtyRef = useRef<Record<string, any>>({});
  const saveInFlight = useRef(false);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<Record<string, any>>("/api/config", { signal: controller.signal, cache: "no-store" })
      .then((data) => { const loaded = data.config && typeof data.config === "object" ? data.config : data; configRef.current = loaded; setConfig(loaded); setStatus("idle"); })
      .catch((err) => { if (!controller.signal.aborted) { setError(errorMessage(err, "Could not load settings.")); setStatus("error"); } });
    return () => controller.abort();
  }, []);

  const updateConfig = (key: string, value: any) => {
    configRef.current = { ...configRef.current, [key]: value };
    setConfig(configRef.current);
    dirtyRef.current = { ...dirtyRef.current, [key]: value };
    setError(null);
  };

  const updateSecret = (key: string, value: string) => {
    setSecretDrafts((prev) => ({ ...prev, [key]: value }));
    setDeleteSecrets((prev) => prev.filter((item) => item !== key));
    setError(null);
  };

  const clearSecret = (key: string) => {
    setSecretDrafts((prev) => ({ ...prev, [key]: "" }));
    setDeleteSecrets((prev) => prev.includes(key) ? prev : [...prev, key]);
  };

  const saveConfig = async () => {
    if (saveInFlight.current) return;
    saveInFlight.current = true;
    setStatus("saving"); setError(null);
    const submittedDirty = { ...dirtyRef.current };
    const submittedDrafts = Object.fromEntries(Object.entries(secretDrafts).filter(([, value]) => value.length > 0));
    const submittedDeletes = deleteSecrets;
    try {
      const response = await apiRequest<{ config?: Record<string, any> }>("/api/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...submittedDirty, ...submittedDrafts, delete_secrets: submittedDeletes }),
      });
      const saved = response.config || {};
      const keepLocal: Record<string, any> = {};
      for (const key of Object.keys(dirtyRef.current)) if (configRef.current[key] !== submittedDirty[key]) keepLocal[key] = configRef.current[key];
      configRef.current = { ...saved, ...keepLocal };
      setConfig(configRef.current);
      dirtyRef.current = Object.fromEntries(Object.entries(dirtyRef.current).filter(([key, value]) => submittedDirty[key] !== value));
      setSecretDrafts((current) => Object.fromEntries(Object.entries(current).filter(([key, value]) => value !== submittedDrafts[key])));
      setDeleteSecrets((current) => current.filter((key) => !submittedDeletes.includes(key)));
      setStatus("saved"); setTimeout(() => setStatus((value) => value === "saved" ? "idle" : value), 2000);
    } catch (err) {
      setError(errorMessage(err, "Could not save settings.")); setStatus("error");
    } finally {
      saveInFlight.current = false;
    }
  };

  return <ConfigContext.Provider value={{ config, updateConfig, secretDrafts, updateSecret, clearSecret, saveConfig, status, error }}>{children}</ConfigContext.Provider>;
}

export function useConfig() {
  const context = useContext(ConfigContext);
  if (!context) throw new Error("useConfig must be used within a ConfigProvider");
  return context;
}
