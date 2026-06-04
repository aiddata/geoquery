import { text } from "@sveltejs/kit";

// Kubernetes readiness probe target. The adapter-node server answering here is
// sufficient signal that the frontend is ready to serve traffic.
export function GET() {
  return text("ready\n");
}
