// Defaults. Put your own values in config.local.js next to this file (gitignored), e.g.
//   export default { media: "https://media.your-domain.com" };
// Its keys override these. media: where the Worker serves trips.json and the trips.
// This site's own origin must be in the Worker's SITE_ORIGINS (worker/wrangler.toml).
export default {
  media: "https://media.example.com",
  title: "Wander",
};
