/**
 * The guided demo: the seven parts of the pitch, cut into steps on the real screens.
 * Each step goes to a screen, points at one thing and stays as long as the presenter speaks there.
 * The words and the presenter's notes are not here on purpose: this ships in the public bundle.
 * `click` is only set on controls that navigate or open something locally (checked against the API calls);
 * Publish, answering a question and reading a notice write the shared state and are never clicked.
 */

export type Target = { sel?: string; text?: string | RegExp; within?: string; nth?: number };

export type Step = {
  beat: number;
  /** go here first (no-op when already there) */
  url?: string;
  /** what the cursor points at; the step waits for it */
  target?: Target;
  /** really click the target once the cursor is on it (read-only controls only) */
  click?: boolean;
  /** seconds on this step once its target is on screen */
  dur: number;
  /** wait after the target appears, before the cursor moves (ms) */
  settle?: number;
  /** give up on the target after this long and go on without it (ms, default 15 000) */
  wait?: number;
  /** remount the page when it is already open (the replay reads ?redare only on mount) */
  fresh?: boolean;
};

export const BEATS = [
  { n: 1, title: "Linia 23" },
  { n: 2, title: "Platforma" },
  { n: 3, title: "Primăria planifică" },
  { n: 4, title: "STPT anunță" },
  { n: 5, title: "STPT verifică" },
  { n: 6, title: "SMTT raportează" },
  { n: 7, title: "Final" },
];

export const HERO_ID = "cl_20261108_16dec";
const LINE23 = "/app/linii/R_AB_23?redare=09:20";
const HERO = `/app/lucrari/${HERO_ID}`;
const MOCIONI = "/app/lucrari/cl_20261102_mocioni/teren";
const RAIL = 'nav[aria-label="Secțiunile platformei"]';
const rail = (label: string): Target => ({ within: RAIL, sel: "a", text: label });

export const STEPS: Step[] = [
  // 1 · line 23 on Saturday, the replay paused at 09:20
  { beat: 1, url: LINE23, fresh: true, dur: 5.3 },
  { beat: 1, url: LINE23, target: { sel: "span", text: /^\s*09:20\s*$/ }, wait: 8000, dur: 9.5 },
  { beat: 1, url: LINE23, target: { sel: 'button[aria-label="Redă"]' }, click: true, wait: 4000, dur: 7.9 },
  { beat: 1, url: LINE23, target: { sel: "li", text: /(^|\D)0 din 68(\D|$)/ }, wait: 6000, dur: 5.3 },

  // 2 · the platform of three institutions: Azi
  { beat: 2, target: rail("Azi"), click: true, dur: 9.1 },
  { beat: 2, url: "/app", target: { text: "înregistrat la 15 secunde" }, wait: 8000, dur: 13.1 },
  { beat: 2, url: "/app", target: { sel: `a[href="${HERO}/impact"]` }, wait: 6000, dur: 10.7 },
  { beat: 2, url: "/app", target: { sel: 'a[href="/app/linii/R_TV_4"]' }, wait: 5000, dur: 9.1 },

  // 3 · the City Hall plans a work
  { beat: 3, url: "/app", target: { sel: `a[href="${HERO}/impact"]` }, click: true, dur: 9.5 },
  { beat: 3, url: `${HERO}/impact`, target: { sel: "dl", text: "plecări pierdute" }, dur: 12.7 },
  { beat: 3, url: `${HERO}/impact`, target: { sel: "button[aria-expanded]", text: "Oprește tramvaiul 7" }, click: true, wait: 6000, dur: 11.1 },
  { beat: 3, url: `${HERO}/impact`, target: { sel: "button", text: "Compară perioadele" }, click: true, dur: 4.2 },
  { beat: 3, url: `${HERO}/perioada`, target: { sel: "li", text: "Cel mai mic impact" }, dur: 7.3 },

  // 4 · STPT announces once, in every format
  { beat: 4, url: `${HERO}/perioada`, target: { sel: "button", text: "Pregătește anunțul" }, click: true, dur: 9.1 },
  { beat: 4, url: `${HERO}/anunt`, target: { text: "Catedrala Mitropolitană" }, wait: 8000, dur: 8.7 },
  { beat: 4, url: `${HERO}/anunt`, target: { sel: "button", text: "Publică lucrarea" }, wait: 2500, dur: 12 }, // pointed at, never clicked
  { beat: 4, url: `${HERO}/anunt`, target: { sel: "button", text: "Cod QR" }, click: true, wait: 5000, dur: 7.3 },

  // 5 · STPT checks the street
  { beat: 5, url: MOCIONI, target: { text: "treceri fără oprire" }, wait: 12000, dur: 12.3 },
  { beat: 5, url: MOCIONI, target: { text: "opriri totuși" }, wait: 4000, dur: 5.1 },
  { beat: 5, target: rail("Linii"), click: true, dur: 2.8 },
  { beat: 5, url: "/app/linii", target: { text: /58 de linii/ }, wait: 8000, dur: 6.3 },

  // 6 · SMTT and the EU get their reports
  { beat: 6, target: rail("Rapoarte"), click: true, dur: 3.5 },
  { beat: 6, url: "/app/rapoarte", target: { sel: "p", text: /^\s*(În \d+ zile închise|Într-o zi închisă)/ }, wait: 10000, dur: 12.9 },
  { beat: 6, url: "/app/rapoarte", target: { sel: '[role="tab"]', text: "Obligații" }, click: true, wait: 4000, dur: 9.9 },

  // 7 · the simulated clock, said plainly
  { beat: 7, target: { within: RAIL, sel: "button", text: "simulat" }, wait: 4000, dur: 9 },
];
