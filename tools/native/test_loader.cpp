#include "loaderCustom.hpp"
#include "pxiRomFS.hpp"
#include <assert.h>
#include <string.h>
#include <stdio.h>

namespace ArticFunctions {
Result loaderInitCustom();
void loaderExitCustom();
Result LOADER_GetLastApplicationProgramInfo(ExHeader_Info*);
}

static u32 commands[128], staticBuffers[2];
static struct Trace {
    u32 values[4];
    unsigned count{};
    void clear() { count = 0; }
    void push_back(u32 value) { assert(count < 4); values[count++] = value; }
    bool empty() const { return count == 0; }
    bool equal(u32 first, u32 second = 0, u32 third = 0) const {
        const u32 expected[] = {first, second, third};
        if (count != (third ? 3u : second ? 2u : 1u)) return false;
        for (unsigned index = 0; index < count; ++index)
            if (values[index] != expected[index]) return false;
        return true;
    }
} calls;
static int closed;
static u32 failCommand;
static bool transportFailure;
static Result serviceInitResult;
static ExHeader_Info* destination;
static constexpr u64 titleId = 0x0004000000055D00;
static constexpr u64 programHandle = 0x123456789ABCDEF0;
namespace ArticFunctions {
Result ReadPxiProgramRomFS(u64 program, u64 offset, u32 size, void*, u32* read, u64* fileSize) {
    assert(program == programHandle && offset == 0 && size == 512);
    *read = size;
    *fileSize = 4096;
    return 0;
}
void ProbePxiProgramRomFS(PxiRomFSReport* report, u64 program) {
    assert(program == programHandle);
    *report = {};
    report->stage = 5;
    report->size = 4096;
}
}
static Result openResult, sizeResult, closeResult;
static unsigned filesClosed;

Result FSUSER_OpenFileDirectly(Handle* file, FS_ArchiveID archive, FS_Path arch,
                               FS_Path path, u32 flags, u32 attributes) {
    assert(static_cast<u32>(archive) == 0x2345678E);
    assert(arch.type == PATH_BINARY && arch.size == 8);
    u64 actual;
    memcpy(&actual, arch.data, 8);
    assert(actual == programHandle);
    const u32 expected[] = {0, 0, 0};
    assert(path.type == PATH_BINARY && path.size == 12);
    assert(memcmp(path.data, expected, 12) == 0);
    assert(flags == FS_OPEN_READ && attributes == 0);
    *file = 73;
    return openResult;
}
Result FSFILE_GetSize(Handle file, u64* size) {
    assert(file == 73);
    *size = 12345;
    return sizeResult;
}
Result FSFILE_Close(Handle file) {
    assert(file == 73);
    ++filesClosed;
    return closeResult;
}

u32* getThreadCommandBuffer() { return commands; }
u32* getThreadStaticBuffers() { return staticBuffers; }
Result srvGetServiceHandle(Handle* handle, const char* name) {
    assert(strcmp(name, "Loader") == 0);
    *handle = 42;
    return serviceInitResult;
}
Result svcCloseHandle(Handle handle) { assert(handle == 42); ++closed; return 0; }
Result svcSendSyncRequest(Handle handle) {
    assert(handle == 42);
    u32 id = commands[0] >> 16;
    calls.push_back(id);
    if (id == 2) {
        assert(commands[0] == IPC_MakeHeader(2, 8, 0));
        FS_ProgramInfo title, update;
        memcpy(&title, commands + 1, sizeof(title));
        memcpy(&update, commands + 5, sizeof(update));
        assert(title.programId == titleId && title.mediaType == 1);
        assert(memcmp(&title, &update, sizeof(title)) == 0);
        memcpy(commands + 2, &programHandle, sizeof(programHandle));
    } else if (id == 4 || id == 0x102) {
        assert(staticBuffers[0] == IPC_Desc_StaticBuffer(0x400, 0));
        assert(staticBuffers[1] == static_cast<u32>(reinterpret_cast<uintptr_t>(destination)));
        if (id == 4) {
            assert(commands[0] == IPC_MakeHeader(4, 2, 0));
            u64 actual;
            memcpy(&actual, commands + 1, sizeof(actual));
            assert(actual == programHandle);
        }
        if (id != failCommand) memset(destination, 0x5A, sizeof(*destination));
    } else {
        assert(id == 3 && commands[0] == IPC_MakeHeader(3, 2, 0));
        u64 actual;
        memcpy(&actual, commands + 1, sizeof(actual));
        assert(actual == programHandle);
        assert(staticBuffers[0] == 0x111 && staticBuffers[1] == 0x222);
    }
    if (id == failCommand && transportFailure) return -123;
    commands[1] = id == failCommand ? static_cast<u32>(-456) : 0;
    return 0;
}

static void reset(ExHeader_Info& output) {
    calls.clear(); closed = 0; failCommand = 0; transportFailure = false;
    serviceInitResult = 0; destination = &output;
    staticBuffers[0] = 0x111; staticBuffers[1] = 0x222;
    memset(&output, 0, sizeof(output));
    openResult = sizeResult = closeResult = 0;
    filesClosed = 0;
}

int main() {
    ExHeader_Info output;
    reset(output);
    assert(ArticFunctions::LOADER_GetTitleProgramInfo(&output, titleId, 1) == 0);
    assert(calls.equal(2, 4, 3));
    assert(output.data[0] == 0x5A && closed == 1);
    const u32 failingCommands[] = {2, 4, 3};
    const bool transports[] = {false, true};
    for (u32 command : failingCommands) {
        for (bool transport : transports) {
            reset(output); failCommand = command; transportFailure = transport;
            assert(ArticFunctions::LOADER_GetTitleProgramInfo(&output, titleId, 1) == (transport ? -123 : -456));
            assert(closed == 1);
            assert(staticBuffers[0] == 0x111 && staticBuffers[1] == 0x222);
            assert(command == 2 ? calls.equal(2) : calls.equal(2, 4, 3));
        }
    }
    reset(output); serviceInitResult = -99;
    assert(ArticFunctions::LOADER_GetTitleProgramInfo(&output, titleId, 1) == -99);
    assert(calls.empty() && closed == 0);
    reset(output); failCommand = 0x102; transportFailure = true;
    assert(ArticFunctions::loaderInitCustom() == 0);
    assert(ArticFunctions::LOADER_GetLastApplicationProgramInfo(&output) == -123);
    assert(staticBuffers[0] == 0x111 && staticBuffers[1] == 0x222);
    ArticFunctions::loaderExitCustom();
    for (unsigned failure = 0; failure < 6; ++failure) {
        reset(output);
        if (failure == 1) openResult = -31;
        if (failure == 2) sizeResult = -32;
        if (failure == 3) closeResult = -33;
        if (failure == 4) failCommand = 2;
        if (failure == 5) failCommand = 3;
        u64 size = 99;
        const Result expected[] = {0, -31, -32, -33, -456, -456};
        assert(ArticFunctions::LOADER_ProbeTitleRomFS(&size, titleId, 1) == expected[failure]);
        assert(calls.equal(2, failure == 4 ? 0 : 3));
        assert(closed == 1);
        assert(filesClosed == ((failure == 1 || failure == 4) ? 0u : 1u));
        if (failure == 0) assert(size == 12345);
    }
    puts("Loader IPC tests passed: success, init failure, command failures, cleanup and static-buffer restoration.");
    reset(output);
    ArticFunctions::PxiRomFSReport report;
    ArticFunctions::LOADER_ProbeTitleRomFSPXI(&report, titleId, 1);
    assert(calls.equal(2, 3) && closed == 1 && report.size == 4096 && report.result == 0);
    reset(output);
    u32 read;
    u64 size;
    assert(ArticFunctions::LOADER_ReadTitleRomFSPXI(nullptr, 512, 0, &read, &size, titleId, 1) == 0);
    assert(calls.equal(2, 3) && closed == 1 && read == 512 && size == 4096);
}
