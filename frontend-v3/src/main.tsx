import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { Landing } from "./landing/Landing";
import { App } from "./app/App";

const isApp = location.pathname === "/app" || location.pathname.startsWith("/app/");

createRoot(document.getElementById("root")!).render(<StrictMode>{isApp ? <App /> : <Landing />}</StrictMode>);
