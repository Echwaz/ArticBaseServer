#include "pxiRomFS.hpp"
#include <3ds/services/fspxi.h>
#include <cassert>
#include <cstdarg>
#include <cstring>
#include <vector>
extern "C" {
#include "csvc.h"
}

static unsigned fail, shortRead;
static bool programMode;
static std::vector<unsigned> calls;
static Result step(unsigned stage) {
    calls.push_back(stage);
    return stage == fail ? -static_cast<Result>(stage) : 0;
}
Result svcControlService(ServiceOp op, ...) {
    assert(op == SERVICEOP_STEAL_CLIENT_SESSION);
    va_list args;
    va_start(args, op);
    *va_arg(args, Handle*) = 42;
    assert(std::strcmp(va_arg(args, const char*), "PxiFS0") == 0);
    va_end(args);
    return step(1);
}
Result svcCloseHandle(Handle handle) {
    assert(handle == 42);
    return step(8);
}
Result FSPXI_OpenArchive(Handle h, FSPXI_Archive* out, FS_ArchiveID id, FS_Path p) {
    assert(h == 42 && static_cast<u32>(id) == (programMode ? 0x2345678E : 0x2345678A));
    if (programMode) {
        u64 program;
        assert(p.type == PATH_BINARY && p.size == 8);
        std::memcpy(&program, p.data, 8);
        assert(program == 0xABCDEF123ULL);
    } else {
    const u32 expected[] = {0x8202, 0x40030, 0, 0};
    assert(p.type == PATH_BINARY && p.size == sizeof(expected));
    assert(std::memcmp(p.data, expected, sizeof(expected)) == 0);
    }
    *out = 0x123456789ULL;
    return step(2);
}
Result FSPXI_OpenFile(Handle h, FSPXI_File* out, FSPXI_Archive a, FS_Path p, u32 f, u32 attrs) {
    assert(h == 42 && a == 0x123456789ULL && f == FS_OPEN_READ && attrs == 0);
    const u32 expected[5]{};
    assert(p.type == PATH_BINARY && p.size == (programMode ? 12 : sizeof(expected)));
    assert(std::memcmp(p.data, expected, p.size) == 0);
    *out = 0x987654321ULL;
    return step(3);
}
Result FSPXI_GetFileSize(Handle h, FSPXI_File f, u64* size) {
    assert(h == 42 && f == 0x987654321ULL);
    *size = 0x4000;
    return step(4);
}
Result FSPXI_ReadFile(Handle h, FSPXI_File f, u32* read, u64 off, void* data, u32 size) {
    assert(h == 42 && f == 0x987654321ULL && off == 0 && size == 512);
    assert(reinterpret_cast<uintptr_t>(data) % 32 == 0);
    *read = shortRead ? 4 : size;
    std::memcpy(data, "IVFC", 4);
    return step(5);
}
Result FSPXI_CloseFile(Handle h, FSPXI_File f) {
    assert(h == 42 && f == 0x987654321ULL);
    return step(6);
}
Result FSPXI_CloseArchive(Handle h, FSPXI_Archive a) {
    assert(h == 42 && a == 0x123456789ULL);
    return step(7);
}
int main() {
    for (fail = 0; fail <= 7; ++fail) {
        calls.clear();
        ArticFunctions::PxiRomFSReport report;
        ArticFunctions::ProbePxiRomFS(&report);
        std::vector<unsigned> expected{1};
        if (fail != 1) {
            expected.push_back(2);
            if (fail != 2) {
                expected.push_back(3);
                if (fail != 3) {
                    expected.push_back(4);
                    if (fail != 4) expected.push_back(5);
                    expected.push_back(6);
                }
                expected.push_back(7);
            }
            expected.push_back(8);
        }
        assert(calls == expected);
        assert(report.result == (fail > 0 && fail <= 5 ? -static_cast<Result>(fail) : 0));
        if (fail == 0) assert(std::memcmp(report.magic, "IVFC", 4) == 0);
        if (fail == 6) assert(report.fileClose == -6);
        if (fail == 7) assert(report.archiveClose == -7);
    }
    fail = 0;
    shortRead = 1;
    ArticFunctions::PxiRomFSReport report;
    ArticFunctions::ProbePxiRomFS(&report);
    const u8 zero[4]{};
    assert(std::memcmp(report.magic, zero, 4) == 0);
    shortRead = 0;
    programMode = true;
    ArticFunctions::ProbePxiProgramRomFS(&report, 0xABCDEF123ULL);
    assert(report.result == 0 && std::memcmp(report.magic, "IVFC", 4) == 0);
    alignas(32) u8 data[512];
    u32 read;
    u64 size;
    for (fail = 0; fail <= 8; ++fail) {
        calls.clear();
        const auto result = ArticFunctions::ReadPxiProgramRomFS(
            0xABCDEF123ULL, 0, sizeof(data), data, &read, &size);
        assert(result == -static_cast<Result>(fail));
        if (fail != 1) assert(calls.back() == 8);
    }
    fail = 0;
    calls.clear();
    assert(ArticFunctions::ReadPxiProgramRomFS(0xABCDEF123ULL, 0x4000, 1,
        data, &read, &size) == static_cast<Result>(0xE0E046C1));
    assert(read == 0 && calls == std::vector<unsigned>({1, 2, 3, 4, 6, 7, 8}));
}
