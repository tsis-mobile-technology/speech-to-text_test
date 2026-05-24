/** @type {import('next').Next.jsConfig} */
const nextConfig = {
  reactStrictMode: true,
  // API 프록시 설정 (개발 편의성)
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://backend:8000/api/:path*', // Docker 내 백엔드 서비스
      },
    ];
  },
};

module.exports = nextConfig;
