#pragma once
#include "3ds.h"

namespace ArticFunctions {
    struct PxiRomFSReport;
    Result LOADER_GetTitleProgramInfo(ExHeader_Info* output, u64 titleId, u8 mediaType);
    Result LOADER_ProbeTitleRomFS(u64* size, u64 titleId, u8 mediaType);
    void LOADER_ProbeTitleRomFSPXI(PxiRomFSReport* report, u64 titleId, u8 mediaType);
    Result LOADER_ReadTitleRomFSPXI(void* data, u32 size, u64 offset,
                                  u32* bytesRead, u64* fileSize, u64 titleId, u8 mediaType, bool update = false);
    Result LOADER_ReadTitleCode(void* data, u32 capacity, u32* bytesRead, u64 titleId, u8 mediaType);
    Result LOADER_GetTitleCodeSize(u64* size, u64 titleId, u8 mediaType);
    void LOADER_CloseRomFSCache();
}
