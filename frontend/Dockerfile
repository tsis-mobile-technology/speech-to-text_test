FROM node:18-alpine

WORKDIR /app

COPY package.json ./

# 의존성 설치
RUN npm install

# 소스코드 복사
COPY . .

EXPOSE 3000

# Next.js 개발 서버 실행 (포트 3000)
CMD ["npm", "run", "dev"]
