# Backup / restore tool image: pg_dump + age (encryption) + rclone (Cloudflare R2 upload).
FROM alpine:3.21
RUN apk add --no-cache bash postgresql16-client age rclone tzdata ca-certificates \
 && adduser -D -u 10002 backup
COPY deploy/scripts/backup.sh deploy/scripts/restore.sh /opt/
RUN chmod 0755 /opt/backup.sh /opt/restore.sh
USER backup
WORKDIR /home/backup
ENTRYPOINT []
CMD ["/opt/backup.sh"]
