#pragma once
#include "3ds.h"
#include <3ds/services/fspxi.h>

namespace ArticFunctions {
struct PxiReadSession {
    Handle service{};
    FSPXI_Archive archive{};
    FSPXI_File file{};
    u64 size{};
    bool archiveOpen{};
    bool fileOpen{};
};
Result OpenPxiProgramFile(PxiReadSession& session, u64 program, bool code);
Result ReadPxiProgramFile(PxiReadSession& session, u64 offset, u32 size, void* output, u32* read);
void ClosePxiProgramFile(PxiReadSession& session);
struct PxiRomFSReport {
    u32 stage;
    Result result;
    u64 size;
    u32 bytesRead;
    u8 magic[4];
    Result fileClose;
    Result archiveClose;
};
static_assert(sizeof(PxiRomFSReport) == 32);
void ProbePxiRomFS(PxiRomFSReport* report);
void ProbePxiProgramRomFS(PxiRomFSReport* report, u64 program);
Result ReadPxiProgramRomFS(u64 program, u64 offset, u32 size, void* data,
                          u32* bytesRead, u64* fileSize);
Result ReadPxiHomeLayout(void* data, u32 size, u32* stage);
}
