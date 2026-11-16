// Canonical host and scheme: www.fmcp27.com and plain http go to https://fmcp27.com
// with a 301, keeping path and query. Everything else falls through to the static site.
export async function onRequest({ request, next }) {
  const url = new URL(request.url);
  const wrongHost = url.hostname === "www.fmcp27.com";
  const plainHttp = url.protocol === "http:" && url.hostname.endsWith("fmcp27.com");
  if (wrongHost || plainHttp) {
    url.hostname = "fmcp27.com";
    url.protocol = "https:";
    url.port = "";
    return Response.redirect(url.toString(), 301);
  }
  return next();
}
