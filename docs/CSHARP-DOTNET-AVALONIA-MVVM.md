# Architectural Standard: Avalonia UI with .NET 10 (MVVM Core)

## 1. Core Philosophy & Cross-Platform Boundaries
- **Framework Stack:** Use .NET 10 paired with Avalonia UI (v11+ setup standards). Maintain strict adherence to the Model-View-ViewModel (MVVM) structural pattern.
- **Linux Native Target:** Optimize development for Linux (Arch, Debian, Fedora packaging targets). Never include system-level dependencies or directory structures unique to Windows (`registry`, `AppData`, backslash file paths). Use cross-platform abstractions like `System.IO.Path.Combine`.

## 2. UI Modularity (AXAML / Code-Behind)
- **Separation of Concerns:** Keep AXAML view markup pure. Code-behind files (`.axaml.cs`) must remain brainless, containing only the standard initialization constructor. 
- **Event Handling Rule:** Multi-layered visual rendering triggers or user button clicks must bind directly to the underlying ViewModel via `ReactiveCommand` or modern compiled bindings (`x:DataType`). Never inject backend database or business logic into code-behind files.
- **Example Data Binding Contract:**
  ```xml
  <!-- MainWindow.axaml -->
  <Window xmlns="https://github.com"
          xmlns:x="http://microsoft.com"
          xmlns:vm="clr-namespace:YourApp.ViewModels"
          x:DataType="vm:MainWindowViewModel">
      <StackPanel Margin="20">
          <TextBlock Text="{Binding SystemStatusMessage}" Classes="Heading" />
          <Button Content="Execute Low-Level Sync" Command="{Binding RunSyncCommand}" />
      </StackPanel>
  </Window>
  ```

## 3. ViewModel Logic & State Management
- **Property Notification:** All observable properties inside ViewModels must use the modern .NET CommunityToolkit.Mvvm source generators. Decorate properties with `[ObservableProperty]` and commands with `[RelayCommand]`. Do not write manual `INotifyPropertyChanged` backing fields.
- **Thread Safety Isolation:** Background computation tasks or low-level module responses must execute asynchronously on background threads using `Task.Run`. If a background response needs to alter the visual UI state, always marshal the property update back to the main UI loop via `Dispatcher.UIThread.Post()`.

## 4. Linux Packaging & Release Compilation
- **Target Distributions:** Package separately for Arch Linux (`.tar.zst`), Debian/Ubuntu (`.deb`), and Fedora/RHEL (`.rpm`).
- **Build Target Optimizations:** The compilation release script must explicitly use the `-c Release` runtime parameter. Enforce single-binary self-contained extraction via these `.csproj` properties to eliminate the requirement for end-users to have the .NET SDK pre-installed:
  ```xml
  <PropertyGroup>
    <PublishSingleFile>true</PublishSingleFile>
    <PublishReadyToRun>true</PublishReadyToRun>
    <SelfContained>true</SelfContained>
    <RuntimeIdentifier>linux-x64</RuntimeIdentifier>
    <PublishTrimmed>true</PublishTrimmed> <!-- Cuts out unused Avalonia/Dotnet DLL assemblies -->
  </PropertyGroup>
  ```
