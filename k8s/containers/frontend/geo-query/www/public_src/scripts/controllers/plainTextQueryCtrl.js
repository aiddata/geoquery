angular.module('aiddataDET')
.controller('PlainTextQueryCtrl', function($scope, $rootScope, $log, queryFactory) {
  // $scope.dataset = '';
  // $scope.geography = '';
  // $scope.filters = [];
  // $scope.options = [];
  // $scope.editable = bool;

  function updateQueryStructure () {
    var q = [
      { value: [$scope.dataset.title] || [], pre: 'Extract data from ', optional: false },
      { value: [$scope.geography] || [], pre: 'within ', optional: false }
    ];

    if ($scope.dataset.type === 'raster') {
      q.push(
        { value: _.get($scope.options, 'options.extract_types') || [], pre: 'calculating', optional: true, key: 'options.extract_types' },
        { value: getYears() || [], pre: 'in', optional: true, key: 'files' }
      );

    } else {
      _.each($scope.filters, function(filterValue, filterId) {
        /* TODO: Stop storing dataset as filter */
        if (filterId !== 'dataset') {
          var filterObj = {
            value: _.get($scope.dataset, ['fields', filterId, 'filter_type']) === 'slider' &&
              !_.isEqual($scope.filters[filterId], ['All']) ? getRange(filterId) :
              _.sortBy(_.filter($scope.filters[filterId], function(d) { return d !== 'All'; })),
            pre: ' where ' + _.get($scope.dataset, ['fields', filterId, 'display']) + ' includes ',
            optional: true,
            key: filterId
          };

          if (filterObj.value.length >= 1) { q.push(filterObj); }
        }
      });
    }
    return _.filter(q, function(option) { return option.value.length >= 1; });
  }

  $scope.removeFilter = function(filter, option) {
    if ($scope.dataset.type !== 'release') {
      var optionData = option.display ? _.omit(option, ['display', '$$hashKey']) : option;
      queryFactory.toggleOptionOff(filter, optionData);
      $rootScope.$broadcast('options:updated', { key: filter, value: optionData, direction: 'off' });
    } else if ($scope.dataset.fields[filter].filter_type === 'list'){
      queryFactory.toggleFilterOff(filter, option);
    } else {
      queryFactory.resetFilterRange(filter);
    }
  };

  function getRange(filterId) {
    var min = d3.format(',')(_.chain($scope.filters[filterId]).min().floor().value()),
        max = d3.format(',')(_.chain($scope.filters[filterId]).max().ceil().value()),
        rangeString = min === max ? '$' + min :
          '$' + min + ' - ' + max;

    return [ rangeString ];
  }

  function getYears() {
    return _.chain($scope.options)
      .get('files')
      .each(function(file) {
        file.display = _.last(_.split(file.name, "_"));
      })
      .value();
  }

  function init () {
    $scope.queryStructure = updateQueryStructure();

    if ($scope.editable) {
      $scope.$watch('filters', function(newValue) {
        $scope.queryStructure = updateQueryStructure();
      }, true);

      $scope.$watch('options', function(newValue) {
        $scope.queryStructure = updateQueryStructure();
      }, true);

      $scope.$watch('dataset', function(newValue) {
        $scope.queryStructure = updateQueryStructure();
      }, true);
    }
  }
  init();

});
