import type { APIRoute } from "astro";

import { securityTxtResponse } from "../lib/securityTxt";

export const GET: APIRoute = ({ site }) =>
  securityTxtResponse(site, import.meta.env.BASE_URL);
