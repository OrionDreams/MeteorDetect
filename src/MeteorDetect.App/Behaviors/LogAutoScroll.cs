using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Threading;
using Avalonia.VisualTree;

namespace MeteorDetect.App.Behaviors;

public sealed class LogAutoScroll
{
    private LogAutoScroll()
    {
    }

    public static readonly AttachedProperty<bool> AutoScrollToEndProperty =
        AvaloniaProperty.RegisterAttached<LogAutoScroll, TextBox, bool>("AutoScrollToEnd");

    private static readonly Dictionary<TextBox, State> States = [];

    static LogAutoScroll()
    {
        AutoScrollToEndProperty.Changed.AddClassHandler<TextBox>(OnAutoScrollToEndChanged);
    }

    public static bool GetAutoScrollToEnd(TextBox textBox) =>
        textBox.GetValue(AutoScrollToEndProperty);

    public static void SetAutoScrollToEnd(TextBox textBox, bool value) =>
        textBox.SetValue(AutoScrollToEndProperty, value);

    private static void OnAutoScrollToEndChanged(TextBox textBox, AvaloniaPropertyChangedEventArgs args)
    {
        if (args.NewValue is true)
        {
            Enable(textBox);
        }
        else
        {
            Disable(textBox);
        }
    }

    private static void Enable(TextBox textBox)
    {
        if (States.ContainsKey(textBox))
        {
            return;
        }

        var state = new State();
        States[textBox] = state;

        state.AttachedToVisualTree = (_, _) => AttachScrollViewer(textBox, state);
        state.DetachedFromVisualTree = (_, _) => Disable(textBox);
        state.PropertyChanged = (_, args) =>
        {
            if (args.Property == TextBox.TextProperty && state.IsAtBottom)
            {
                Dispatcher.UIThread.Post(() => state.ScrollViewer?.ScrollToEnd(), DispatcherPriority.Background);
            }
        };

        textBox.AttachedToVisualTree += state.AttachedToVisualTree;
        textBox.DetachedFromVisualTree += state.DetachedFromVisualTree;
        textBox.PropertyChanged += state.PropertyChanged;

        if (textBox.IsAttachedToVisualTree())
        {
            AttachScrollViewer(textBox, state);
        }
    }

    private static void Disable(TextBox textBox)
    {
        if (!States.Remove(textBox, out var state))
        {
            return;
        }

        textBox.AttachedToVisualTree -= state.AttachedToVisualTree;
        textBox.DetachedFromVisualTree -= state.DetachedFromVisualTree;
        textBox.PropertyChanged -= state.PropertyChanged;

        if (state.ScrollViewer is not null)
        {
            state.ScrollViewer.ScrollChanged -= state.ScrollChanged;
        }
    }

    private static void AttachScrollViewer(TextBox textBox, State state)
    {
        Dispatcher.UIThread.Post(() =>
        {
            var scrollViewer = textBox.GetVisualDescendants().OfType<ScrollViewer>().FirstOrDefault();
            if (scrollViewer is null || ReferenceEquals(scrollViewer, state.ScrollViewer))
            {
                return;
            }

            if (state.ScrollViewer is not null)
            {
                state.ScrollViewer.ScrollChanged -= state.ScrollChanged;
            }

            state.ScrollViewer = scrollViewer;
            state.IsAtBottom = IsScrolledToBottom(scrollViewer);
            scrollViewer.ScrollChanged += state.ScrollChanged;

            if (state.IsAtBottom)
            {
                scrollViewer.ScrollToEnd();
            }
        }, DispatcherPriority.Loaded);
    }

    private static bool IsScrolledToBottom(ScrollViewer scrollViewer)
    {
        var maximumOffset = Math.Max(0, scrollViewer.Extent.Height - scrollViewer.Viewport.Height);
        return scrollViewer.Offset.Y >= maximumOffset - 1;
    }

    private sealed class State
    {
        public bool IsAtBottom { get; set; } = true;

        public ScrollViewer? ScrollViewer { get; set; }

        public EventHandler<VisualTreeAttachmentEventArgs>? AttachedToVisualTree { get; set; }

        public EventHandler<VisualTreeAttachmentEventArgs>? DetachedFromVisualTree { get; set; }

        public EventHandler<AvaloniaPropertyChangedEventArgs>? PropertyChanged { get; set; }

        public EventHandler<ScrollChangedEventArgs> ScrollChanged { get; }

        public State()
        {
            ScrollChanged = (sender, _) =>
            {
                if (sender is ScrollViewer scrollViewer)
                {
                    IsAtBottom = IsScrolledToBottom(scrollViewer);
                }
            };
        }
    }
}
