/**
 * The pitch as the guided demo plays it: the seven beats of the table round, cut into steps.
 * Each step goes to a screen, points at one thing, and shows the words to say while pointing at it.
 * `click` is only set on controls that navigate or open something locally (checked against the API calls);
 * Publish, answering a question and reading a notice write the shared state and are never clicked.
 */

export type Target = { sel?: string; text?: string | RegExp; within?: string; nth?: number };

export type Step = {
  beat: number;
  /** go here first (no-op when already there) */
  url?: string;
  /** what the cursor points at; the step waits for it (up to 20 s) */
  target?: Target;
  /** really click the target once the cursor is on it (read-only controls only) */
  click?: boolean;
  /** what Erol clicks at the table, said in the note */
  press?: string;
  /** the words to say; {x} is filled from the screen by `fill` */
  say: string;
  /** where to point, what to know */
  note?: string;
  fill?: (el: HTMLElement) => Record<string, string>;
  /** extra seconds after the last word */
  hold?: number;
  /** wait after the target appears, before the cursor moves (ms) */
  settle?: number;
  /** give up on the target after this long and go on without it (ms, default 15 000) */
  wait?: number;
  /** remount the page when it is already open (the replay reads ?redare only on mount) */
  fresh?: boolean;
  /** values used when the target is not on the screen */
  defaults?: Record<string, string>;
};

export const BEATS = [
  { n: 1, title: "Cârligul", at: "0:00" },
  { n: 2, title: "Platforma", at: "0:20" },
  { n: 3, title: "Primăria planifică", at: "0:50" },
  { n: 4, title: "STPT anunță", at: "1:30" },
  { n: 5, title: "STPT verifică", at: "2:05" },
  { n: 6, title: "SMTT raportează", at: "2:25" },
  { n: 7, title: "Încheierea", at: "2:50" },
];

export const HERO_ID = "cl_20261108_16dec";
const LINE23 = "/app/linii/R_AB_23?redare=09:20";
const HERO = `/app/lucrari/${HERO_ID}`;

const ofText = (el: HTMLElement) => (el.textContent ?? "").replace(/\s+/g, " ");
/** „174 din 223” from the row, as it is on the screen now. */
const din = (el: HTMLElement): Record<string, string> => { const m = ofText(el).match(/(\d[\d.]*)\s*din\s*(\d[\d.]*)/); return m ? { x: `${m[1]} din ${m[2]}` } : {}; };

const RAIL = 'nav[aria-label="Secțiunile platformei"]';
const rail = (label: string): Target => ({ within: RAIL, sel: "a", text: label });

export const STEPS: Step[] = [
  // 1 · the hook, on the line page with the replay paused at 09:20
  { beat: 1, url: LINE23, fresh: true, hold: 1.6,
    say: "Orarul nu e un tabel. E o promisiune.",
    note: "Te uiți la juriu, nu la ecran. O pauză scurtă după „promisiune”." },
  { beat: 1, url: LINE23, target: { sel: "span", text: /^\s*09:20\s*$/ }, wait: 8000,
    say: "Sâmbătă, la 9:20, eram în stație la Liceul Calderon și așteptam 23. După orar, trebuia să vină. N-a venit.",
    note: "Ora redării, 09:20 sâmbătă. Povestea e a ta: o spui la persoana întâi." },
  { beat: 1, url: LINE23, target: { sel: 'button[aria-label="Redă"]' }, click: true, wait: 4000, press: "▶ Redă, abia după „N-a venit.”",
    say: "În datele live ale Primăriei, linia 23 n-a avut niciun vehicul toată ziua de sâmbătă.",
    note: "Pe hartă, linia 23 e punctată: niciun vehicul pe ea, în timp ce restul rețelei se mișcă." },
  { beat: 1, url: LINE23, target: { sel: "li", text: /(^|\D)0 din 68(\D|$)/ }, wait: 6000, hold: 2,
    say: "68 de curse în orar. Zero văzute.",
    note: "Rândul „sâm., 14 nov. · 0 din 68”. Spui „sâmbătă”, niciodată „acum”: azi linia 23 circulă din nou." },

  // 2 · what the platform is: the back office of three institutions, behind CityApp
  { beat: 2, target: rail("Azi"), click: true, press: "Azi",
    say: "Promisiunea asta o țin trei instituții. Primăria aprobă lucrările. STPT circulă și informează oamenii. SMTT plătește și verifică.",
    note: "Numești instituțiile pe rând. Ele sunt utilizatorii; cetățeanul vede doar rezultatul." },
  { beat: 2, url: "/app", target: { text: "înregistrat la 15 secunde" }, wait: 8000,
    say: "Fiecare are datele ei: orarul la SMTT, pozițiile autobuzelor la Primărie, lucrările într-un text pe site-ul STPT. Trei insule. Rețeaua Vie e platforma lor comună, în spatele CityApp.",
    note: "Cuvântul cheie e „complementar”: CityApp e ce vede cetățeanul, noi suntem biroul din spate. Nu înlocuim nimic." },
  { beat: 2, url: "/app", target: { sel: `a[href="${HERO}/impact"]` }, wait: 6000,
    say: "Așa începe ziua lor: ce așteaptă un om, lucrările nepublicate, liniile fără vehicul. Opt surse intră, patru familii de fișiere standard ies.",
    note: "Ecranul Azi: sus, ce așteaptă o decizie; dedesubt, liniile cu cele mai multe curse nevăzute." },
  { beat: 2, url: "/app", target: { sel: 'a[href="/app/linii/R_TV_4"]' }, wait: 5000, fill: din, defaults: { x: "o parte" },
    say: "Și comparația cu strada merge non-stop: la tramvaiul 4, doar {x} de curse au apărut în datele live.",
    note: "Rândul tramvaiului 4. Citești cifra de pe ecran: crește în timpul zilei." },

  // 3 · the City Hall plans a work
  { beat: 3, url: "/app", target: { sel: `a[href="${HERO}/impact"]` }, click: true, press: "rândul Bd. 16 Decembrie, „Deschide”",
    say: "Primul lucru, pentru Primărie: lucrările. STPT a anunțat lucrări pe Bd. 16 Decembrie, duminică, de la 10 la 18.",
    note: "Dacă primul rând e o lucrare lipită de altcineva, n-ai resetat: rulezi resetul după juriu." },
  { beat: 3, url: `${HERO}/impact`, target: { sel: "dl", text: "plecări pierdute" }, hold: 1.8,
    say: "Înainte să semneze, Primăria vede costul estimat: 16 stații fără serviciu. 2.262 de plecări pierdute. 1.845 de locuitori fără nicio stație deservită la 400 de metri.",
    note: "Cele trei cifre. Sunt estimări pe orarul planificat, și ecranul o spune. Partea măsurată vine la Mocioni." },
  { beat: 3, url: `${HERO}/impact`, target: { sel: "button[aria-expanded]", text: "Oprește tramvaiul 7" }, click: true, wait: 6000, press: "întrebarea 1: o deschizi, nu răspunzi",
    say: "Anunțul l-a citit platforma singură, cu reguli fixe. Unde nu e clar, nu ghicește: întreabă omul, și îi arată linia stație cu stație.",
    note: "Harta încadrează porțiunea întrebată. Nu apeși „Oprește” sau „Nu oprește”: asta scrie în platformă." },
  { beat: 3, url: `${HERO}/impact`, target: { sel: "button", text: "Compară perioadele" }, click: true, press: "Compară perioadele", hold: 0.5,
    say: "Apoi caută fereastra care strică cel mai puțin:" },
  { beat: 3, url: `${HERO}/perioada`, target: { sel: "li", text: "Cel mai mic impact" }, hold: 2,
    say: "aceleași 8 ore, sâmbătă noaptea. 500 de plecări în loc de 2.262.",
    note: "Rândul verde „Cel mai mic impact · 500”. Primăria decide, platforma doar propune." },

  // 4 · STPT announces, once, for every channel
  { beat: 4, url: `${HERO}/perioada`, target: { sel: "button", text: "Pregătește anunțul" }, click: true, press: "Pregătește anunțul",
    say: "Al doilea lucru, pentru STPT: anunțul. Azi e un text pe site, rescris de mână pentru fiecare canal." },
  { beat: 4, url: `${HERO}/anunt`, target: { text: "Catedrala Mitropolitană" }, wait: 8000,
    say: "Al nostru numește fiecare stație, ce linii nu mai opresc acolo și cea mai apropiată stație deservită.",
    note: "Lista „Afișe pentru stații”: fiecare stație are afișul ei, cu cod QR și versiune audio." },
  { beat: 4, url: `${HERO}/anunt`, target: { sel: "button", text: "Publică lucrarea" }, wait: 2500, // gone once someone published: the demo goes on
    say: "Un om confirmă o dată, și ies toate formatele: alerta GTFS-Realtime pe care o pot citi CityApp și Google, DATEX II și NGSI-LD pentru sistemele europene, și afișul din stație, cu cod QR și versiune audio.",
    note: "La masă, Erol apasă „Publică lucrarea”, apoi „Da, publică acum”. Demo-ul nu apasă: site-ul e public. Spui „pot citi”, nu „citesc”." },
  { beat: 4, url: `${HERO}/anunt`, target: { sel: "button", text: "Cod QR" }, click: true, wait: 5000, press: "Cod QR, la Catedrala Mitropolitană", hold: 4,
    say: "Scanați codul: e afișul de la Catedrală.",
    note: "Taci 3–4 secunde cât scanează juriul. Întorci laptopul spre telefonul lor." },

  // 5 · STPT checks the street
  { beat: 5, url: "/app/lucrari/cl_20261102_mocioni/teren", target: { text: "treceri fără oprire" }, wait: 12000,
    fill: (el) => { const m = (el.textContent ?? "").match(/(\d[\d.]*)\s*(de\s*)?treceri/); const v = m ? Number(m[1].replace(/\./g, "")) : 0; return { n: v >= 20 ? `peste ${Math.floor(v / 10) * 10}` : "peste 270" }; },
    defaults: { n: "peste 270" },
    say: "Al treilea lucru: verificarea pe stradă. La Piața Mocioni, liniile sunt deviate. Am numărat {n} de treceri pe lângă stațiile scoase de pe traseu. Nicio oprire.",
    note: "Măsurat, nu modelat: la fiecare trecere, înregistrarea spune dacă vehiculul a oprit. Citești cifra și o rotunjești în jos." },
  { beat: 5, url: "/app/lucrari/cl_20261102_mocioni/teren", target: { text: "opriri totuși" }, wait: 4000,
    say: "Deci devierea chiar se respectă: măsurat, nu presupus." },
  { beat: 5, target: rail("Linii"), click: true, press: "Linii", hold: 0.3,
    say: "Și dispeceratul vede la fel" },
  { beat: 5, url: "/app/linii", target: { text: /58 de linii/ }, wait: 8000, hold: 1.4,
    say: "toate cele 58 de linii, cu vehiculele lor și cursele nevăzute.",
    note: "Subtitlul: 58 de linii și vehiculele din datele live acum. Erol poate deschide orice linie cerută de juriu." },

  // 6 · SMTT and the EU get their reports
  { beat: 6, target: rail("Rapoarte"), click: true, press: "Rapoarte", hold: 0.6,
    say: "Al patrulea lucru, pentru SMTT: rapoartele." },
  { beat: 6, url: "/app/rapoarte", target: { sel: "p", text: /^\s*(În \d+ zile închise|Într-o zi închisă)/ }, wait: 10000, fill: din, defaults: { x: "4.454 din 4.779" }, hold: 1.6,
    say: "SMTT plătește STPT pe curse, după raportul STPT. Noi îi dăm o numărătoare independentă, zi de zi, sigilată: în primele două zile, {x} de curse din orar.",
    note: "Fraza de sus din Rapoarte. Fără nicio sumă în lei: încadrarea curselor e treaba SMTT." },
  { beat: 6, url: "/app/rapoarte", target: { sel: '[role="tab"]', text: "Obligații" }, click: true, wait: 4000, press: "fila Obligații", hold: 1.4,
    say: "Și obligațiile de date de transport: exporturile MMTIS și metadatele pentru Punctul Național de Acces ies gata, fără muncă manuală.",
    note: "Spui „exporturile sunt gata”, nu „suntem conformi”: obligația UE 2024/490 e încă de verificat." },

  // 7 · who gains, one more week, the hand-over, the honest close
  { beat: 7, hold: 1.2,
    say: "Pe scurt: Primăria decide pe cifre. STPT scrie o singură dată. SMTT verifică independent. Iar omul din stație află exact ce nu mai merge și unde să meargă.",
    note: "Patru câștiguri, unul pe instituție și unul pentru cetățean. Fără „pilot”, fără „ce cerem”." },
  { beat: 7, hold: 1.2,
    say: "Dacă mai aveam o săptămână: unu, CityApp legat la alertele noastre. Doi, check-in în vehicule, ca să vedem și autobuzele cu GPS-ul oprit. Trei, cititorul de anunțuri testat pe toate anunțurile STPT din ultimul an.",
    note: "Ce am construi, nu ce cerem." },
  { beat: 7, hold: 1.6,
    say: "Totul merge pe date pe care orașul le are deja, pe un singur server, cu cod deschis. Primăria îl poate rula fără noi.",
    note: "Spui „cod deschis” doar dacă repo-ul e public." },
  { beat: 7, target: { within: RAIL, sel: "button", text: "simulat" }, wait: 4000, hold: 2.2,
    say: "Și un lucru spus cinstit: lucrarea din demo e din 8 noiembrie, așa că ceasul e dat înapoi. Scrie aici: „simulat”. Vehiculele, în schimb, sunt reale, înregistrate de noi.",
    note: "Eticheta de jos din bară: „simulat”. Apoi: „Mulțumim. Întrebări?”" },
];
