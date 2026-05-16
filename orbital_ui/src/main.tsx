import * as ReactDOM from "react-dom/client";

import App from "./App";
import "./index.css";

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error('Missing document element with id "root"');
}

ReactDOM.createRoot(rootEl).render(<App />);
