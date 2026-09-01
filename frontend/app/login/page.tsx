"use client";

import { useRouter } from "next/navigation";

import { api, errorMessage, setSession } from "@/lib/api";
import { AuthForm } from "../ui";

export default function LoginPage() {
  const router = useRouter();

  return (
    <AuthForm
      title="Sign in"
      submitLabel="Sign in"
      extra={
        <p className="muted">
          No account? <a href="/register">Register</a>
        </p>
      }
      onSubmit={async (email, password) => {
        try {
          const data = await api<{ token: string; email: string }>("/api/auth/login/", {
            method: "POST",
            body: JSON.stringify({ email, password }),
          });
          setSession(data.token, data.email);
          router.replace("/");
        } catch (err) {
          throw new Error(errorMessage(err));
        }
      }}
    />
  );
}
