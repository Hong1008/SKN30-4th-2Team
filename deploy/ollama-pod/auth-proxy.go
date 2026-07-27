// Ollama Pod 앞단에서 Bearer 토큰을 확인하는 최소 reverse proxy다.
package main

import (
	"crypto/subtle"
	"encoding/json"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
)

const (
	listenAddress = ":11434"
	upstreamURL   = "http://127.0.0.1:11435"
)

func authorized(request *http.Request, requiredToken string) bool {
	if requiredToken == "" {
		return true
	}
	suppliedToken, ok := strings.CutPrefix(request.Header.Get("Authorization"), "Bearer ")
	return ok && subtle.ConstantTimeCompare([]byte(suppliedToken), []byte(requiredToken)) == 1
}

func writeJSON(response http.ResponseWriter, status int, body map[string]string) {
	response.Header().Set("Content-Type", "application/json; charset=utf-8")
	response.WriteHeader(status)
	_ = json.NewEncoder(response).Encode(body)
}

func main() {
	target, err := url.Parse(upstreamURL)
	if err != nil {
		log.Fatalf("Ollama upstream URL is invalid: %v", err)
	}
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorHandler = func(response http.ResponseWriter, _ *http.Request, proxyErr error) {
		log.Printf("Ollama upstream request failed: %v", proxyErr)
		writeJSON(response, http.StatusBadGateway, map[string]string{"detail": "ollama unavailable"})
	}
	requiredToken := os.Getenv("POD_API_KEY")

	handler := http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/health" {
			writeJSON(response, http.StatusOK, map[string]string{"status": "READY"})
			return
		}
		if !authorized(request, requiredToken) {
			writeJSON(response, http.StatusUnauthorized, map[string]string{"detail": "invalid authorization"})
			return
		}
		// Ollama 자체에는 인증이 필요 없으므로 검증된 토큰을 내부 upstream에 전달하지 않는다.
		request.Header.Del("Authorization")
		proxy.ServeHTTP(response, request)
	})

	log.Printf("Ollama 인증 proxy가 http://0.0.0.0%s에서 대기합니다.", listenAddress)
	log.Fatal(http.ListenAndServe(listenAddress, handler))
}
