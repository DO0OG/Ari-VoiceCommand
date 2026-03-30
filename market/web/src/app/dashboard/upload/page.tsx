import { Suspense } from "react";
import { UploadForm } from "@/components/UploadForm";
import { UpdateBanner } from "@/components/UpdateBanner";

export default function UploadPage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-12">
      <Suspense>
        <UpdateBanner />
      </Suspense>
      <UploadForm />
    </main>
  );
}
