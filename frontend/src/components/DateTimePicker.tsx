import React, { useState, useEffect } from 'react';
import { format } from 'date-fns';
import { CalendarIcon, Clock, ChevronUp, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Calendar } from '@/components/ui/calendar';

interface DateTimePickerProps {
  value?: Date;
  onChange: (date: Date | undefined) => void;
  placeholder?: string;
  className?: string;
}

interface TimeInputProps {
  value: number;
  onChange: (value: number) => void;
  max: number;
  min?: number;
  step?: number;
  label: string;
}

const TimeInput: React.FC<TimeInputProps> = ({ 
  value, 
  onChange, 
  max, 
  min = 0, 
  step = 1,
  label 
}) => {
  const handleIncrement = () => {
    const newValue = value + step;
    if (newValue <= max) {
      onChange(newValue);
    } else {
      onChange(min);
    }
  };

  const handleDecrement = () => {
    const newValue = value - step;
    if (newValue >= min) {
      onChange(newValue);
    } else {
      onChange(max);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const inputValue = parseInt(e.target.value);
    if (!isNaN(inputValue) && inputValue >= min && inputValue <= max) {
      onChange(inputValue);
    }
  };

  return (
    <div className="flex flex-col items-center space-y-1">
      <label className="text-xs text-muted-foreground">{label}</label>
      <div className="flex flex-col items-center">
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-8 p-0 hover:bg-muted"
          onClick={handleIncrement}
        >
          <ChevronUp className="h-3 w-3" />
        </Button>
        <Input
          type="number"
          value={value.toString().padStart(2, '0')}
          onChange={handleInputChange}
          className="w-12 h-8 text-center text-sm border-0 bg-transparent p-0 focus-visible:ring-0"
          min={min}
          max={max}
        />
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-8 p-0 hover:bg-muted"
          onClick={handleDecrement}
        >
          <ChevronDown className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
};

export const DateTimePicker: React.FC<DateTimePickerProps> = ({
  value,
  onChange,
  placeholder = "Pick a date and time",
  className
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedDate, setSelectedDate] = useState<Date | undefined>(value);
  const [hours, setHours] = useState(value ? value.getHours() : 0);
  const [minutes, setMinutes] = useState(value ? value.getMinutes() : 0);

  // Sync with parent value prop
  useEffect(() => {
    if (value && value !== selectedDate) {
      setSelectedDate(value);
      setHours(value.getHours());
      setMinutes(value.getMinutes());
    } else if (!value) {
      setSelectedDate(undefined);
      setHours(0);
      setMinutes(0);
    }
  }, [value, selectedDate]);

  const createDateTime = (date: Date, hours: number, minutes: number): Date => {
    const newDate = new Date(date);
    newDate.setHours(hours, minutes, 0, 0);
    return newDate;
  };

  const handleDateSelect = (date: Date | undefined) => {
    if (date) {
      const newDateTime = createDateTime(date, hours, minutes);
      setSelectedDate(newDateTime);
    } else {
      setSelectedDate(undefined);
    }
  };

  const handleTimeChange = (newHours: number, newMinutes: number) => {
    setHours(newHours);
    setMinutes(newMinutes);
    
    if (selectedDate) {
      const newDateTime = createDateTime(selectedDate, newHours, newMinutes);
      setSelectedDate(newDateTime);
    }
  };

  const handleHoursChange = (newHours: number) => {
    handleTimeChange(newHours, minutes);
  };

  const handleMinutesChange = (newMinutes: number) => {
    handleTimeChange(hours, newMinutes);
  };

  const handleApply = () => {
    onChange(selectedDate);
    setIsOpen(false);
  };

  const handleClear = () => {
    setSelectedDate(undefined);
    setHours(0);
    setMinutes(0);
    onChange(undefined);
    setIsOpen(false);
  };

  const handleToday = () => {
    const now = new Date();
    setSelectedDate(now);
    setHours(now.getHours());
    setMinutes(now.getMinutes());
  };

  const handleNow = () => {
    const now = new Date();
    const newDateTime = createDateTime(selectedDate || now, now.getHours(), now.getMinutes());
    setSelectedDate(newDateTime);
    setHours(now.getHours());
    setMinutes(now.getMinutes());
  };

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "justify-start text-left font-normal",
            !value && "text-muted-foreground",
            className
          )}
        >
          <CalendarIcon className="mr-2 h-4 w-4" />
          {value ? format(value, "dd.MM.yyyy HH:mm") : placeholder}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <div className="p-3">
          <Calendar
            mode="single"
            selected={selectedDate}
            onSelect={handleDateSelect}
            initialFocus
          />
          
          {/* Time Selection */}
          <div className="border-t pt-4 mt-3">
            <div className="flex items-center gap-2 mb-4">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Time</span>
            </div>
            
            <div className="flex items-center justify-center gap-4 mb-4">
              <TimeInput
                value={hours}
                onChange={handleHoursChange}
                max={23}
                min={0}
                label="Hours"
              />
              
              <div className="flex items-center pt-6">
                <span className="text-lg font-medium text-muted-foreground">:</span>
              </div>
              
              <TimeInput
                value={minutes}
                onChange={handleMinutesChange}
                max={59}
                min={0}
                step={1}
                label="Minutes"
              />
            </div>
            
            <div className="flex justify-center mb-3">
              <Button
                size="sm"
                variant="outline"
                onClick={handleNow}
                className="text-xs"
              >
                Now
              </Button>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2 pt-3 border-t">
            <Button size="sm" variant="outline" onClick={handleToday} className="flex-1">
              Today
            </Button>
            <Button size="sm" variant="outline" onClick={handleClear} className="flex-1">
              Clear
            </Button>
            <Button size="sm" onClick={handleApply} className="flex-1">
              Apply
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
};

export default DateTimePicker;