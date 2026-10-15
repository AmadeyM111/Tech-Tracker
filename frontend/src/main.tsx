import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { Providers } from "./app/providers";
import "./shared/ui/ui.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("root element not found");
}

createRoot(container).render(
  <StrictMode>
    <Providers>
      <App />
    </Providers>
  </StrictMode>,
);
