// Your media host: where the Worker serves trips.json and the trips (no trailing slash).
// This site's own origin must be in the Worker's SITE_ORIGINS (worker/wrangler.toml).
export default {
  media: "https://media.example.com",
  title: "Wander",
};
