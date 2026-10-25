export const PROVIDERS = [
  {
    id: "groq",
    name: "Groq",
    optional: false,
    url: "https://console.groq.com/keys",
    steps: ["Create or sign in to your Groq account.", "Open API Keys and create a key.", "Copy it here; it is encrypted on the backend."],
  },
  {
    id: "gemini",
    name: "Gemini",
    optional: false,
    url: "https://aistudio.google.com/apikey",
    steps: ["Sign in to Google AI Studio.", "Choose Create API key.", "Copy the key here; keep it private."],
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    optional: false,
    url: "https://openrouter.ai/keys",
    steps: ["Sign in to OpenRouter.", "Create a key from the Keys page.", "Copy the key here; it will not be stored in this browser."],
  },
  {
    id: "weather",
    name: "OpenWeatherMap",
    optional: true,
    url: "https://home.openweathermap.org/api_keys",
    steps: ["Create an OpenWeatherMap account.", "Open API keys and copy an active key.", "Weather is optional; add it only if you use weather features."],
  },
] as const;

export type ProviderId = (typeof PROVIDERS)[number]["id"];
