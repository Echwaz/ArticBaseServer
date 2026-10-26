ifeq ($(strip $(DEVKITARM)),)
$(error DEVKITARM is required)
endif
include $(DEVKITARM)/3ds_rules

PREFIX := $(DEVKITARM)/bin/arm-none-eabi-
MAKEROM ?= makerom
SOURCE := ../plugin
CPP := $(wildcard $(SOURCE)/sources/*.cpp $(SOURCE)/sources/CTRPluginFramework/*.cpp $(SOURCE)/ArticProtocol/sources/*.cpp)
C := $(wildcard $(SOURCE)/sources/*.c)
ASM := $(SOURCE)/sources/csvc.s
OBJECTS := $(addprefix build/,$(notdir $(CPP:.cpp=.o) $(C:.c=.o) $(ASM:.s=.o)))
VPATH := $(SOURCE)/sources:$(SOURCE)/sources/CTRPluginFramework:$(SOURCE)/ArticProtocol/sources
ARCH := -march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft
FLAGS := $(ARCH) -Os -ffunction-sections -fdata-sections -D__3DS__ -DARTIC_STANDALONE \
         -DVERSION_MAJOR=1 -DVERSION_MINOR=2 -DVERSION_REVISION=0 -DSERVER_PORT=5543 \
         -I$(SOURCE)/includes -I$(SOURCE)/ArticProtocol/includes -I$(CTRULIB)/include

.PHONY: all
all: ArticDockTest.3dsx

build:
	mkdir -p build

build/%.o: %.cpp | build
	$(PREFIX)g++ $(FLAGS) -std=gnu++20 -fno-exceptions -fno-rtti -MMD -MP -c $< -o $@

build/%.o: %.c | build
	$(PREFIX)gcc $(FLAGS) -MMD -MP -c $< -o $@

build/%.o: %.s | build
	$(PREFIX)gcc $(ARCH) -c $< -o $@

build/ArticDockTest.elf: $(OBJECTS)
	$(PREFIX)g++ $(ARCH) -specs=3dsx.specs -Wl,--gc-sections -Wl,-Map,build/ArticDockTest.map \
        $^ -L$(CTRULIB)/lib -lctru -lm -o $@

ArticDockTest.smdh:
	smdhtool --create "Artic Dock Test" "Experimental standalone title reader" "Local development" \
        $(DEVKITPRO)/libctru/default_icon.png $@

ArticDockTest.3dsx: build/ArticDockTest.elf ArticDockTest.smdh
	3dsxtool $< $@ --smdh=ArticDockTest.smdh

ArticDockTest.cia: build/ArticDockTest.elf ArticDockTest.smdh ArticDockTest.rsf romfs/test.txt
	$(MAKEROM) -f cia -o $@ -elf $< -rsf ArticDockTest.rsf -icon ArticDockTest.smdh -target t

-include $(OBJECTS:.o=.d)
