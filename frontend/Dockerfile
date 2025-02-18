# Use Node.js image to build the app
FROM node:23-alpine3.20

# Set the working directory
WORKDIR /app

# Copy package.json and yarn.lock
COPY package.json yarn.lock ./

# Install dependencies
RUN yarn install

# Copy the rest of your project
COPY . .

# Expose the port Vite will run on (default is 5173 for development)
EXPOSE 5173

# Start Vite's dev server
CMD ["yarn", "dev"]
