FROM node:18-alpine AS build

WORKDIR /app

# Copy package.json and package-lock.json
COPY package*.json ./

# Copy the rest of the frontend code
COPY . .

# Install dependencies
RUN npm install

# Build the app
RUN npm run build

# Expose port 80
EXPOSE 3001

# Build for production
CMD npm start