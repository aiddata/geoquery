angular.module('aiddataDET')
  .factory('filterFactory', function(ajaxFactory) {


    return {
      filters: { },

      filterOptions: { },

      updateFilters: function () {
        var self = this;

        return ajaxFactory.filters(self.filters)
          .then(function(results) {
            var filterOptions = self.filterOptions = results.data;
            filterOptions.filterTypes = _.keys(filterOptions.distinct);

            return filterOptions;
          }, function(err) {
            console.log(err);
          });
      },

      setDataset: function(datasetName) {
        this.filters.dataset = datasetName;
      },

      isChecked: function (filter, option) {
        return this.filters[filter] &&
          this.filters[filter].indexOf(option) >= 0;
      },

      allChecked: function () {

      },

      toggleFilter: function (filter, option) {
        var dir = !this.isChecked(filter, option);

        if (dir === true) {
        // Toggle On
          if (!this.filters[filter]) {
            this.filters[filter] = [];
          }
          this.filters[filter].push(option);
        } else {
        // Toggle Off
          _.pull(this.filters[filter], option);
          if (!this.filters[filter].length) {
            delete this.filters[filter];
          }
        }
        return this.filters;
      }


    };
  });
