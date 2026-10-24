import type { Job } from "@/lib/types";
export function Portfolio({ jobs }: { jobs: Job[] }) {
  return <section><h2>Portfolio overview</h2><p><strong>{jobs.length}</strong> workloads loaded</p>
    <p>Official spend and realized savings will come from backend metrics.</p></section>;
}
