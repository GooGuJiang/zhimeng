import { PlayView } from "./PlayView";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PlayView id={id} />;
}
