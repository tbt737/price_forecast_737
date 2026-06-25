// Cloudflare Worker entrypoint: forwards every HTTP request to the FastAPI
// container and injects the DATABASE_URL secret into the container's environment.
import { Container } from "@cloudflare/containers";

export class ApiContainer extends Container {
  defaultPort = 8000; // uvicorn port (apps/api/Dockerfile EXPOSE 8000)
  sleepAfter = "10m"; // scale to zero after 10 min idle

  constructor(ctx, env) {
    super(ctx, env);
    // The container reads DATABASE_URL from its environment (set this as a Worker
    // secret: `wrangler secret put DATABASE_URL` = the Supabase SESSION POOLER url).
    this.envVars = { DATABASE_URL: env.DATABASE_URL };
  }
}

export default {
  async fetch(request, env) {
    // Single shared instance; the in-process forecast cache lives there.
    return env.API_CONTAINER.getByName("api").fetch(request);
  },
};
