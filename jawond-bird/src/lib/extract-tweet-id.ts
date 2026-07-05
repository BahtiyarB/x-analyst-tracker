/**
 * Extract tweet ID from a Twitter/X URL or return the input unchanged if it's already an ID.
 */
export function extractTweetId(input: string): string {
  // If it's a URL, extract the tweet ID
  const urlMatch = input.match(/(?:twitter\.com|x\.com)\/\w+\/status\/(\d+)/);
  if (urlMatch) {
    return urlMatch[1];
  }
  // Assume it's already an ID
  return input;
}
