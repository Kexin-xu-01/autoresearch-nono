// Intercept open/openat calls to /proc/<pid>/task/<tid>/comm and
// /proc/self/task/<tid>/comm, redirect to /dev/null.
// This lets CUDA name its threads without needing broad /proc write access.
// Build: gcc -shared -fPIC -O2 -o cuda_proc_shim.so cuda_proc_shim.c -ldl
// Use:   LD_PRELOAD=/path/to/cuda_proc_shim.so python train.py
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <string.h>

static int path_is_proc_comm(const char *path) {
    if (!path || strncmp(path, "/proc/", 6) != 0) return 0;
    const char *p = path + 6;
    // Accept both /proc/<digits>/... and /proc/self/...
    if (strncmp(p, "self/", 5) == 0) {
        p += 5;
    } else {
        if (*p < '0' || *p > '9') return 0;
        while (*p >= '0' && *p <= '9') p++;
        if (*p != '/') return 0;
        p++;
    }
    if (strncmp(p, "task/", 5) != 0) return 0;
    p += 5;
    if (*p < '0' || *p > '9') return 0;
    while (*p >= '0' && *p <= '9') p++;
    return strcmp(p, "/comm") == 0;
}

int open(const char *path, int flags, ...) {
    static int (*real_open)(const char *, int, ...) = NULL;
    if (!real_open) real_open = dlsym(RTLD_NEXT, "open");
    if (path_is_proc_comm(path))
        return real_open("/dev/null", flags & ~O_CREAT);
    va_list ap;
    va_start(ap, flags);
    mode_t mode = (flags & O_CREAT) ? va_arg(ap, mode_t) : 0;
    va_end(ap);
    return real_open(path, flags, mode);
}

int open64(const char *path, int flags, ...) {
    static int (*real_open64)(const char *, int, ...) = NULL;
    if (!real_open64) real_open64 = dlsym(RTLD_NEXT, "open64");
    if (path_is_proc_comm(path))
        return real_open64("/dev/null", flags & ~O_CREAT);
    va_list ap;
    va_start(ap, flags);
    mode_t mode = (flags & O_CREAT) ? va_arg(ap, mode_t) : 0;
    va_end(ap);
    return real_open64(path, flags, mode);
}

int openat(int dirfd, const char *path, int flags, ...) {
    static int (*real_openat)(int, const char *, int, ...) = NULL;
    if (!real_openat) real_openat = dlsym(RTLD_NEXT, "openat");
    if (path_is_proc_comm(path))
        return real_openat(dirfd, "/dev/null", flags & ~O_CREAT);
    va_list ap;
    va_start(ap, flags);
    mode_t mode = (flags & O_CREAT) ? va_arg(ap, mode_t) : 0;
    va_end(ap);
    return real_openat(dirfd, path, flags, mode);
}
