FROM nginx:1.27-alpine
COPY index.html data.xlsx legacy-galleries.json /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
