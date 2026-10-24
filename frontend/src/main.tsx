import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AppBoundary } from "./ui";
import "./style.css";

createRoot(document.getElementById("root")!).render(<StrictMode><AppBoundary><App /></AppBoundary></StrictMode>);
