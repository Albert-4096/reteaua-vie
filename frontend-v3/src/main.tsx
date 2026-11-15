import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { Landing } from "./landing/Landing";
import { App } from "./app/App";
import { StopPage } from "./qr/StopPage";

const isApp = location.pathname === "/app" || location.pathname.startsWith("/app/");
const isStop = location.pathname.startsWith("/a/"); // the phone page behind a poster's QR code

createRoot(document.getElementById("root")!).render(<StrictMode>{isStop ? <StopPage /> : isApp ? <App /> : <Landing />}</StrictMode>);
