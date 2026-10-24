import type { Job } from "@/lib/types";
export function JobBlotter({ jobs }: { jobs: Job[] }) {
  return <section><h2>Workload blotter</h2><table><thead><tr><th>Workload</th><th>Resource</th><th>Deadline slot</th><th>Status</th></tr></thead>
    <tbody>{jobs.map(job => <tr key={job.id}><td>{job.name}</td><td>{job.resourceUnits} × {job.gpuType ?? job.resourceType}</td><td>{job.deadlineSlot}</td><td>{job.status}</td></tr>)}</tbody></table></section>;
}
