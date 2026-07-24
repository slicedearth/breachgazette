const CONTACT =
  "https://github.com/slicedearth/breachgazette/security/advisories/new";
const POLICY = "https://github.com/slicedearth/breachgazette/security/policy";
const EXPIRES = "2027-07-24T00:00:00Z";

export function securityTxtResponse(
  site: URL | undefined,
  baseUrl: string,
): Response {
  if (!site) throw new Error("A canonical site URL is required for security.txt");
  const canonical = new URL(`${baseUrl}.well-known/security.txt`, site).toString();
  const body = [
    `Contact: ${CONTACT}`,
    `Expires: ${EXPIRES}`,
    `Policy: ${POLICY}`,
    "Preferred-Languages: en",
    `Canonical: ${canonical}`,
    "",
  ].join("\n");
  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
