import { motion } from "motion/react";
import { ArrowRight, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, useApi, type Closure } from "@/lib/api";
import { Film } from "@/film/Film";
import { Bento } from "./Bento";
import { CityMap } from "./CityMap";
import { Integration } from "./Integration";
import { Logo } from "./Logo";
import { LogoStrip } from "./LogoMarquee";
import { Proof } from "./Proof";
import { Today } from "./Today";

const APP = "/app";
const CLOSURE_IDS = ["cl_20261102_mocioni", "cl_20261107_e3", "cl_20261108_16dec"];

function Section({ id, title, sub, children }: { id: string; title: string; sub: string; children: React.ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-6xl scroll-mt-24 px-6 pt-36">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="display text-[2.75rem]">{title}</h2>
        <p className="mt-4 text-lg leading-relaxed text-muted-foreground">{sub}</p>
      </div>
      <div className="mt-14">{children}</div>
    </section>
  );
}

function useClosures() {
  return useApi(() => Promise.all(CLOSURE_IDS.map((id) => api.closure(id).catch(() => null))).then((xs) => xs.filter(Boolean) as Closure[]));
}

export function Landing() {
  const closures = useClosures();
  return (
    <div className="dot-ground min-h-dvh">
      <header className="sticky top-0 z-40 border-b border-transparent bg-background/80 backdrop-blur-md">
        <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6" aria-label="Principal">
          <a href="#" className="flex items-center gap-2.5 font-semibold tracking-tight">
            <Logo className="size-8" /> Rețeaua Vie
          </a>
          <div className="hidden items-center gap-8 text-[0.95rem] text-muted-foreground md:flex">
            <a className="transition-colors hover:text-foreground" href="#film">Filmul</a>
            <a className="transition-colors hover:text-foreground" href="#pentru-cine">Pentru cine</a>
            <a className="transition-colors hover:text-foreground" href="#harta">Harta</a>
            <a className="transition-colors hover:text-foreground" href="#integrare">Integrare</a>
          </div>
          <Button asChild size="sm" variant="outline" className="rounded-full">
            <a href={APP}>Deschide platforma</a>
          </Button>
        </nav>
      </header>

      <main>
        <section className="relative mx-auto max-w-6xl px-6 pt-24 text-center">
          <motion.h1 className="display mx-auto max-w-6xl text-[clamp(2.5rem,4.6vw,4rem)]"
            initial={{ opacity: 0, y: 14, filter: "blur(8px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}>
            <span className="block">Lucrarea închide strada.</span>
            <span className="block">Transportul public pierde plecări.</span>
          </motion.h1>
          <motion.p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground"
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}>
            Rețeaua Vie le numără pe orarul SMTT înainte de semnătură, arată ce stații și ce locuitori rămân fără transport și găsește fereastra care face cel mai puțin rău. Pentru Primăria Timișoara, STPT și SMTT.
          </motion.p>
          <motion.div className="mt-9 flex flex-wrap items-center justify-center gap-3"
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}>
            <Button asChild size="lg" className="h-12 rounded-full px-6 text-base shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_8px_20px_-8px_var(--primary)]">
              <a href={APP}>Deschide platforma <ArrowRight className="size-4" /></a>
            </Button>
            <Button asChild size="lg" variant="ghost" className="h-12 rounded-full px-5 text-base">
              <a href="#film"><Play className="size-4" /> Vezi filmul, 48 s</a>
            </Button>
          </motion.div>

          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.8, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}>
            <Proof />
          </motion.div>

          <motion.div id="film" className="mx-auto mt-16 max-w-5xl scroll-mt-24"
            initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 1, delay: 0.45, ease: [0.16, 1, 0.3, 1] }}>
            <Film />
          </motion.div>
        </section>

        <Today />

        <LogoStrip />

        <Section id="pentru-cine" title="Aceeași lucrare. Trei câștiguri."
          sub="Primăria decide pe cifre, STPT publică o singură dată, iar călătorii află din aplicațiile și stațiile pe care le folosesc deja.">
          <Bento />
        </Section>

        <Section id="harta" title="Timișoara, acum."
          sub="Cele 58 de linii în culorile STPT și vehiculele din datele live ale Primăriei, înregistrate de noi la 15 secunde, peste cele 40 de cartiere.">
          <div className="rounded-xl border bg-card p-6 shadow-card md:p-10">
            <CityMap closures={closures.data ?? []} />
          </div>
        </Section>

        <Section id="integrare" title="Datele orașului intră. Informația corectă iese."
          sub="Rețeaua Vie citește ce are deja orașul și scrie în formatele standard pe care le citesc CityApp, Google, Punctul Național de Acces și stațiile.">
          <Integration />
        </Section>

        <section className="mx-auto max-w-6xl px-6 py-36 text-center">
          <h2 className="display text-[2.75rem]">Încercați pe o lucrare reală.</h2>
          <p className="mx-auto mt-4 max-w-xl text-lg text-muted-foreground">Trei lucrări din anunțurile STPT sunt deja în platformă, cu ceasul demo pe 8 noiembrie 2026, ora 12:00.</p>
          <Button asChild size="lg" className="mt-9 h-12 rounded-full px-6 text-base">
            <a href={APP}>Deschide platforma <ArrowRight className="size-4" /></a>
          </Button>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-muted-foreground">
          <span>Rețeaua Vie · UniHack 8, Timișoara · The Bloom: Green Mobility</span>
          <span>Date: SMTT GTFS, endpointurile Primăriei, anunțurile STPT, GHSL 2020 (model)</span>
        </div>
      </footer>
    </div>
  );
}
