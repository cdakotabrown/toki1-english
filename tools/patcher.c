/* patcher.c -- the English patch as one program: it carries english.ppf,
 * checks the player's own Track 1 dump by SHA-1, writes the English Track 1
 * beside it (the original is never changed) and a .cue for the result.
 *
 * Usage: drag the game's .cue or Track 1 .bin onto the program, or put the
 * program in the folder that holds them and start it.
 *
 * Built by tools/patch/make_patcher.py, which generates patcher_gen.h (the
 * checksums of the disc it applies to and of the result) and embeds
 * english.ppf with .incbin.  No game data is in the program beyond what
 * the PPF itself holds (tools/patch/package_ppf.py explains what that is).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "patcher_gen.h" /* TRACK1_SIZE, TRACK1_SHA1, RESULT_SHA1, PPF_PATH */

#ifdef _WIN32
#include <windows.h>
#include <wchar.h>
typedef wchar_t pchar;
#define P(s) L##s
#define PFMT "%ls"
#define p_fopen _wfopen
#define p_len wcslen
#define p_cpy wcscpy
#define p_cat wcscat
#define p_rchr wcsrchr
#define p_icmp _wcsicmp
#define f_seek _fseeki64
#define SEP P('\\')
__asm__(".section .rdata,\"dr\"\n.globl ppf_start\nppf_start:\n.incbin \"" PPF_PATH "\"\n"
        ".globl ppf_end\nppf_end:\n.text\n");
#else
#include <dirent.h>
#include <strings.h>
#include <sys/stat.h>
typedef char pchar;
#define P(s) s
#define PFMT "%s"
#define p_fopen fopen
#define p_len strlen
#define p_cpy strcpy
#define p_cat strcat
#define p_rchr strrchr
#define p_icmp strcasecmp
#define f_seek fseeko
#define SEP '/'
__asm__(".section .rodata\n.globl ppf_start\nppf_start:\n.incbin \"" PPF_PATH "\"\n"
        ".globl ppf_end\nppf_end:\n.text\n");
#endif

extern const unsigned char ppf_start[], ppf_end[];

#define OUT_BIN P("Tokimeki Memorial - Forever with You (English) (Track 1).bin")
#define OUT_CUE P("Tokimeki Memorial - Forever with You (English).cue")
#define DEF_TRACK2 "Tokimeki Memorial - Forever with You (Japan) (Rev 1) (Track 2).bin"
#define PATHMAX 2048

/* ---- SHA-1 ---- */
typedef struct { uint32_t h[5]; uint64_t n; unsigned char b[64]; int used; } Sha1;
static uint32_t rol(uint32_t v, int s) { return (v << s) | (v >> (32 - s)); }
static void sha1_block(Sha1 *c, const unsigned char *p) {
    uint32_t w[80], a = c->h[0], b = c->h[1], d = c->h[2], e = c->h[3], f = c->h[4], t;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    for (i = 0; i < 80; i++) {
        uint32_t k, g;
        if (i < 20) { g = (b & d) | (~b & e); k = 0x5A827999; }
        else if (i < 40) { g = b ^ d ^ e; k = 0x6ED9EBA1; }
        else if (i < 60) { g = (b & d) | (b & e) | (d & e); k = 0x8F1BBCDC; }
        else { g = b ^ d ^ e; k = 0xCA62C1D6; }
        t = rol(a, 5) + g + f + k + w[i];
        f = e; e = d; d = rol(b, 30); b = a; a = t;
    }
    c->h[0] += a; c->h[1] += b; c->h[2] += d; c->h[3] += e; c->h[4] += f;
}
static void sha1_init(Sha1 *c) {
    c->h[0] = 0x67452301; c->h[1] = 0xEFCDAB89; c->h[2] = 0x98BADCFE;
    c->h[3] = 0x10325476; c->h[4] = 0xC3D2E1F0; c->n = 0; c->used = 0;
}
static void sha1_add(Sha1 *c, const unsigned char *p, size_t n) {
    c->n += n;
    while (n) {
        size_t take = 64 - (size_t)c->used;
        if (take > n) take = n;
        memcpy(c->b + c->used, p, take);
        c->used += (int)take; p += take; n -= take;
        if (c->used == 64) { sha1_block(c, c->b); c->used = 0; }
    }
}
static void sha1_hex(Sha1 *c, char out[41]) {
    uint64_t bits = c->n * 8;
    unsigned char pad[72] = { 0x80 }, len[8];
    int i, padn = (c->used < 56 ? 56 : 120) - c->used;
    for (i = 0; i < 8; i++) len[i] = (unsigned char)(bits >> (56 - 8 * i));
    sha1_add(c, pad, (size_t)padn);
    sha1_add(c, len, 8);
    for (i = 0; i < 5; i++) sprintf(out + 8 * i, "%08x", c->h[i]);
}

/* ---- helpers ---- */
static int g_wait;
static int done(int rc) {
    if (g_wait) {
        printf("\nPress Enter to close.");
        fflush(stdout);
        getchar();
    }
    return rc;
}

static int has_ext(const pchar *path, const pchar *ext) {
    size_t n = p_len(path), e = p_len(ext);
    return n > e && !p_icmp(path + n - e, ext);
}

static void dir_of(const pchar *path, pchar *dir) {
    const pchar *s = p_rchr(path, SEP);
#ifdef _WIN32
    const pchar *s2 = p_rchr(path, P('/'));
    if (s2 && (!s || s2 > s)) s = s2;
#endif
    if (!s) { dir[0] = 0; return; }
    memcpy(dir, path, (size_t)(s - path + 1) * sizeof(pchar));
    dir[s - path + 1] = 0;
}

static long long file_size(const pchar *path) {
#ifdef _WIN32
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExW(path, GetFileExInfoStandard, &a)) return -1;
    return ((long long)a.nFileSizeHigh << 32) | a.nFileSizeLow;
#else
    struct stat st;
    return stat(path, &st) ? -1 : (long long)st.st_size;
#endif
}

/* the first *.bin of TRACK1_SIZE bytes in `dir` (not our own output) */
static int find_track1(const pchar *dir, pchar *out) {
#ifdef _WIN32
    pchar pat[PATHMAX];
    WIN32_FIND_DATAW fd;
    HANDLE h;
    p_cpy(pat, dir); p_cat(pat, P("*.bin"));
    h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        long long sz = ((long long)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
        if (sz == TRACK1_SIZE && p_icmp(fd.cFileName, OUT_BIN)) {
            p_cpy(out, dir); p_cat(out, fd.cFileName);
            FindClose(h);
            return 1;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return 0;
#else
    DIR *d = opendir(dir[0] ? dir : ".");
    struct dirent *e;
    if (!d) return 0;
    while ((e = readdir(d))) {
        pchar path[PATHMAX];
        if (!has_ext(e->d_name, ".bin") || !p_icmp(e->d_name, OUT_BIN)) continue;
        snprintf(path, sizeof path, "%s%s", dir, e->d_name);
        if (file_size(path) == TRACK1_SIZE) { p_cpy(out, path); closedir(d); return 1; }
    }
    closedir(d);
    return 0;
#endif
}

/* FILE "name" lines of a cue: the first is Track 1, the second Track 2 */
static void read_cue(const pchar *cue, char names[2][512]) {
    FILE *f = p_fopen(cue, P("rb"));
    char line[1024];
    int n = 0;
    names[0][0] = names[1][0] = 0;
    if (!f) return;
    while (n < 2 && fgets(line, sizeof line, f)) {
        char *a = strstr(line, "FILE \""), *b;
        if (!a) continue;
        a += 6;
        b = strchr(a, '"');
        if (!b || (size_t)(b - a) >= 512) continue;
        memcpy(names[n], a, (size_t)(b - a));
        names[n++][b - a] = 0;
    }
    fclose(f);
}

static void join_name(const pchar *dir, const char *name, pchar *out) {
#ifdef _WIN32
    pchar w[512];
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, name, -1, w, 512))
        MultiByteToWideChar(CP_ACP, 0, name, -1, w, 512);
    p_cpy(out, dir); p_cat(out, w);
#else
    snprintf(out, PATHMAX, "%s%s", dir, name);
#endif
}

#ifdef _WIN32
int wmain(int argc, wchar_t **argv)
#else
int main(int argc, char **argv)
#endif
{
    static unsigned char buf[1 << 20];
    static pchar in[PATHMAX], dir[PATHMAX], out[PATHMAX], cue[PATHMAX];
    char names[2][512] = { "", "" }, hex[41];
    const unsigned char *p = ppf_start + 60, *end = ppf_end;
    FILE *fi, *fo;
    Sha1 sha;
    long long total = 0, nrec = 0;
    size_t n;

#ifdef _WIN32
    {   /* started by a double click or a drop: the console closes with us */
        DWORD pids[2];
        g_wait = GetConsoleProcessList(pids, 2) <= 1;
        SetConsoleOutputCP(CP_UTF8);
    }
#endif
    printf("Tokimeki Memorial: Forever with You -- English patch\n"
           "Unofficial fan translation. Needs your own dump of the Japanese disc\n"
           "(SLPS-00065, Rev 1); it is not changed, a patched copy is written beside it.\n\n");

    if (memcmp(ppf_start, "PPF30", 5) || end - ppf_start < 60) {
        printf("This program is damaged (no patch inside).\n");
        return done(2);
    }

    if (argc > 1) {
        p_cpy(in, argv[1]);
        dir_of(in, dir);
        if (has_ext(in, P(".cue"))) {
            read_cue(in, names);
            if (!names[0][0]) { printf("That .cue names no file.\n"); return done(2); }
            join_name(dir, names[0], in);
        }
    } else {
        dir_of(argv[0], dir);
        if (!find_track1(dir, in)) {
            dir[0] = 0;
            if (!find_track1(dir, in)) {
                printf("Drag the game's .cue or its Track 1 .bin onto this program,\n"
                       "or put this program in the folder that holds them and start it again.\n"
                       "Track 1 is the large .bin: %lld bytes.\n", (long long)TRACK1_SIZE);
                return done(1);
            }
        }
    }

    printf("Disc:   " PFMT "\n", in);
    if (file_size(in) != TRACK1_SIZE) {
        printf("That is not Track 1 of the Rev 1 disc: it should be %lld bytes%s.\n",
               (long long)TRACK1_SIZE, file_size(in) < 0 ? " (file not found)" : "");
        return done(1);
    }
    p_cpy(out, dir); p_cat(out, OUT_BIN);
    p_cpy(cue, dir); p_cat(cue, OUT_CUE);
    if (!p_icmp(in, out)) {     /* never open the input for writing */
        printf("That is the English disc this program writes. Give it the Japanese Track 1.\n");
        return done(1);
    }
    fi = p_fopen(in, P("rb"));
    if (!fi) { printf("Cannot open it.\n"); return done(1); }
    fo = p_fopen(out, P("wb+"));
    if (!fo) { printf("Cannot write " PFMT "\n", out); fclose(fi); return done(1); }

    printf("Checking and copying (about a minute)...\n");
    fflush(stdout);
    sha1_init(&sha);
    while ((n = fread(buf, 1, sizeof buf, fi)) > 0) {
        sha1_add(&sha, buf, n);
        if (fwrite(buf, 1, n, fo) != n) { printf("Disk full or write error.\n"); goto fail; }
        total += (long long)n;
    }
    fclose(fi); fi = NULL;
    sha1_hex(&sha, hex);
    if (!strcmp(hex, RESULT_SHA1)) {
        printf("This disc is already the English one. Nothing to do.\n");
        goto fail;
    }
    if (total != TRACK1_SIZE || strcmp(hex, TRACK1_SHA1)) {
        printf("This is not the disc the patch is for (or the dump is bad).\n"
               "  SHA-1 of your Track 1: %s\n  SHA-1 it needs:        %s\n", hex, TRACK1_SHA1);
        goto fail;
    }

    printf("Patching...\n");
    fflush(stdout);
    while (p + 9 <= end) {
        uint64_t off = 0;
        unsigned len = p[8];
        int i;
        for (i = 7; i >= 0; i--) off = off << 8 | p[i];
        p += 9;
        if (p + len > end || off + len > (uint64_t)TRACK1_SIZE) { printf("Bad patch record.\n"); goto fail; }
        if (f_seek(fo, (long long)off, SEEK_SET) || fwrite(p, 1, len, fo) != len) {
            printf("Write error.\n");
            goto fail;
        }
        p += len;
        nrec++;
    }

    printf("Verifying...\n");
    fflush(stdout);
    fflush(fo);
    f_seek(fo, 0, SEEK_SET);
    sha1_init(&sha);
    while ((n = fread(buf, 1, sizeof buf, fo)) > 0) sha1_add(&sha, buf, n);
    sha1_hex(&sha, hex);
    fclose(fo); fo = NULL;
    if (strcmp(hex, RESULT_SHA1)) {
        printf("The result is not what it should be (SHA-1 %s). It was removed.\n", hex);
        goto fail;
    }

    {   /* the .cue: the English Track 1 and the original audio track */
        FILE *fc = p_fopen(cue, P("wb"));
        if (fc) {
            fprintf(fc, "FILE \"Tokimeki Memorial - Forever with You (English) (Track 1).bin\" BINARY\r\n"
                        "  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n"
                        "FILE \"%s\" BINARY\r\n  TRACK 02 AUDIO\r\n"
                        "    INDEX 00 00:00:00\r\n    INDEX 01 00:02:00\r\n",
                    names[1][0] ? names[1] : DEF_TRACK2);
            fclose(fc);
        }
    }
    printf("\nDone: %lld changes applied and verified.\n\n"
           "English disc: " PFMT "\n"
           "Open this in your emulator: " PFMT "\n"
           "(Keep your Track 2 .bin in the same folder: the .cue uses it.)\n",
           nrec, out, cue);
    return done(0);

fail:
    if (fi) fclose(fi);
    if (fo) fclose(fo);
#ifdef _WIN32
    DeleteFileW(out);
#else
    remove(out);
#endif
    return done(1);
}
