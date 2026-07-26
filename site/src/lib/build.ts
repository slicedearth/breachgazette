const TEST_SOURCE_REVISION = "0".repeat(40);

export function getSourceRevision(): string {
  const configured = process.env.BREACHGAZETTE_SOURCE_REVISION;
  if (!configured && process.env.BREACHGAZETTE_TEST_BUILD === "1") {
    return TEST_SOURCE_REVISION;
  }
  if (!configured || !/^[0-9a-f]{40}$/.test(configured)) {
    throw new Error(
      "BREACHGAZETTE_SOURCE_REVISION must be an exact lowercase 40-character commit",
    );
  }
  return configured;
}
