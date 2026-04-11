import { createContext, useContext, useState } from "react";
import ToastContainer from "./components/Toast";

export type ToastType = "warning" | "error" | "info";

export type Toast = {
  id: number;
  type: ToastType;
  title: string;
  message: string;
};

type PushToast = (toast: Omit<Toast, "id">) => void;

const ToastContext = createContext<PushToast>(() => {});

export function useToast(): PushToast {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push: PushToast = (t) =>
    setToasts((prev) => [...prev, { ...t, id: Date.now() }]);

  const dismiss = (id: number) =>
    setToasts((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={push}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}
