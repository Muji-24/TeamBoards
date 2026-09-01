"use client";

import { useRouter } from "next/navigation";

import { api, errorMessage, setSession } from "@/lib/api";
import { AuthForm } from "../ui";

export default function RegisterPage() {
  const router = useRouter();

  return (
    <AuthForm
      title="Create account"
      submitLabel="Register"
          extra={
            <>
              <p className="muted">
                Already registered? <a href="/login">Sign in</a>
              </p>
              <label className="field">
                <span>Name</span>
                <input name="name" type="text" placeholder="Optional" />
              </label>
            </>
          }
      onSubmit={async (email, password, name) => {
        try {
          const data = await api<{ token: string; email: string }>("/api/auth/register/", {
            method: "POST",
            body: JSON.stringify({ email, password, name }),
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
