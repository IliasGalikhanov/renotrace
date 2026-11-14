import Link from "next/link";
import GuestReview from "./review";
import "./review.css";

export default function ReviewPage() {
  return (
    <main className="guest-shell">
      <header className="guest-header">
        <Link href="/" className="brand">
          RenoTrace
        </Link>
        <span>Private guest review · No account</span>
      </header>
      <div className="guest-intro">
        <p className="eyebrow">YOUR DOCUMENTS, A TRACEABLE CALCULATION</p>
        <h1>Know what your invoice adds up to.</h1>
        <p>
          Upload your invoice, estimate and payment evidence. Check the facts
          before calculating what remains under your recorded terms.
        </p>
      </div>
      <GuestReview />
    </main>
  );
}
