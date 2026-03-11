import { useState, type FormEvent } from "react";

interface Props {
  onSearch: (query: string) => void;
  isLoading: boolean;
}

export default function SearchBar({ onSearch, isLoading }: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = value.trim();
    if (q && !isLoading) onSearch(q);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="glass px-4 py-3 flex items-center gap-3 w-full max-w-xl"
    >
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Describe a region... e.g. 'San Francisco Bay Area'"
        className="flex-1 bg-transparent outline-none text-sm text-white placeholder-neutral-500"
        disabled={isLoading}
      />
      {isLoading ? (
        <div className="w-5 h-5 border-2 border-neutral-500 border-t-white rounded-full animate-spin" />
      ) : (
        <button
          type="submit"
          className="text-sm text-neutral-400 hover:text-white transition-colors px-2"
        >
          &crarr;
        </button>
      )}
    </form>
  );
}
