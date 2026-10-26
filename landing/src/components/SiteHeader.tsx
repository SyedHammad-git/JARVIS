import Link from "next/link";
import { AuthAction } from "@/components/AuthAction";
import { ThemeToggle } from "@/components/ThemeToggle";

const links = [
  { href: "/", label: "Home" },
  { href: "/#features", label: "Features" },
  { href: "/download", label: "Download" },
  { href: "/docs", label: "Docs" },
];

export function SiteHeader() {
  return (
    <header className="site-header">
      <div className="site-width header-inner">
        <Link href="/" className="brand-lockup" aria-label="JARVIS home">
          <span className="brand-mark" aria-hidden="true">J</span><span>J.A.R.V.I.S.</span>
        </Link>
        <nav className="desktop-nav" aria-label="Main navigation">
          {links.map((link) => <Link href={link.href} key={link.label}>{link.label}</Link>)}
        </nav>
        <div className="header-actions">
          <ThemeToggle />
          <AuthAction label="Sign In" className="header-sign-in" />
          <AuthAction label="Sign Up" className="button-primary header-sign-up" />
        </div>
        <details className="mobile-menu">
          <summary aria-label="Open navigation menu"><span aria-hidden="true">☰</span></summary>
          <nav aria-label="Mobile navigation">
            {links.map((link) => <Link href={link.href} key={link.label}>{link.label}</Link>)}
            <AuthAction label="Sign In" className="header-sign-in" />
            <AuthAction label="Sign Up" className="button-primary" />
          </nav>
        </details>
      </div>
    </header>
  );
}
