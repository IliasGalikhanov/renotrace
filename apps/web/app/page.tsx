import DemoExperience from "./demo";

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#workspace">
        Skip to demo
      </a>
      <header className="site-header">
        <a className="brand" href="#" aria-label="RenoTrace home">
          <span className="brand-mark" aria-hidden="true">
            r.
          </span>
          RenoTrace
        </a>
        <span className="synthetic-badge">
          <span aria-hidden="true" />
          Synthetic demo
        </span>
        <a className="header-link" href="#workspace">
          Explore the sample <span aria-hidden="true">↗</span>
        </a>
      </header>
      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow">A LITTLE CLARITY FOR YOUR RENOVATION</p>
            <h1 id="hero-title">
              Know what&apos;s asked.
              <br />
              <em>See what&apos;s recorded.</em>
            </h1>
            <p>
              Trace your contractor&apos;s payment request through the
              agreement, changes and payments. Understand the numbers — and what
              still needs an answer.
            </p>
            <a className="button" href="/review">
              Review my invoice <span aria-hidden="true">↗</span>
            </a>
            <a
              className="sample-link"
              href="#workspace"
              style={{ marginLeft: 20 }}
            >
              Try sample <span aria-hidden="true">↗</span>
            </a>
            <span className="hero-note">
              No account needed. Or explore fictional records with real
              calculations.
            </span>
          </div>
          <div className="hero-graphic" aria-hidden="true">
            <div className="graphic-top">FROM A PILE OF RECORDS</div>
            <div className="paper paper-back">
              <span>Agreement</span>
              <i />
              <i />
              <i />
            </div>
            <div className="paper paper-middle">
              <span>Payments</span>
              <i />
              <i />
            </div>
            <div className="paper paper-front">
              <span className="paper-kicker">RENOTRACE</span>
              <strong>
                A clearer
                <br />
                picture.
              </strong>
              <div className="paper-check">
                ✓ &nbsp; Every amount has a story
              </div>
            </div>
            <div className="graphic-bottom">
              TO A TRACEABLE ANSWER <span>↗</span>
            </div>
          </div>
        </section>
        <DemoExperience />
      </main>
      <footer>
        <span className="brand">RenoTrace</span>
        <p>Clarity before the next payment.</p>
        <span>Synthetic demo · Nothing is saved</span>
      </footer>
    </>
  );
}
