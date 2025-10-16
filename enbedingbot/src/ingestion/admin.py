from django.contrib import admin

from ingestion.models import N8NEmbed, UploadedFile


@admin.register(UploadedFile)
class UploadedFileAdmin(admin.ModelAdmin):
    list_display = ("file_name", "chat_id", "status", "uploaded_at", "processed_at")
    list_filter = ("status", "uploaded_at")
    search_fields = ("file_name", "chat_id")
    readonly_fields = ("uploaded_at", "processed_at", "file_size")


@admin.register(N8NEmbed)
class N8NEmbedAdmin(admin.ModelAdmin):
    list_display = ("tittle",)
    search_fields = ("tittle", "body")
