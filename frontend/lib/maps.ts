/**
 * Google Maps deep links for itinerary places.
 *
 * These are plain search URLs built client-side rather than Places API
 * lookups: an itinerary has ~4 places a day across several days and two
 * compared destinations, so enriching each one would mean dozens of billed
 * API calls and a visible delay, for a link that works just as well
 * without them. Destination cards and hotels DO get real enrichment
 * (photo/rating), because that data arrives free with searches already
 * being made.
 */
export function placeMapsUrl(place: string, destination: string): string {
  const query = encodeURIComponent(`${place}, ${destination}`);
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
}
