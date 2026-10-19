import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <h1 className="h1">此处尚未被织就</h1>
      <p>你要找的页面不存在。</p>
      <Link href="/" className="btn">
        回到开局
      </Link>
    </div>
  );
}
