// Custom Caddy build: upstream v2 with the standard modules plus rate
// limiting, compiled with a current Go toolchain and up-to-date dependencies.
// The official image lags behind on golang.org/x/* and stdlib fixes (17 HIGH
// at the time of writing); rebuilding closes them without waiting for a
// Caddy release.
package main

import (
	caddycmd "github.com/caddyserver/caddy/v2/cmd"

	_ "github.com/caddyserver/caddy/v2/modules/standard"
	// rate_limit HTTP handler (per-client request limits in the Caddyfile).
	_ "github.com/mholt/caddy-ratelimit"
)

func main() {
	caddycmd.Main()
}
